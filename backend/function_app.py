"""Contoso internal systems API: a plain REST API that the gateway (API Management) exposes to Copilot
Studio agents as MCP tools. See docs/architecture.md.

Auth is handled before this code runs:
- The gateway validates the caller's Entra token, the agent's allow-list and any app role.
- Function App built-in auth (Easy Auth) validates the token again and rejects anything without one.
So every request that reaches these handlers carries a valid token for the gateway API.

Tools:
- directory_get_my_profile   Microsoft Graph, as the person (delegated, on-behalf-of)
- finance_list_cost_centres  finance database, as this service (app-only, managed identity)
- finance_query_spend        finance database, as the person (delegated, on-behalf-of)
"""

import base64
import datetime as dt
import json
import os
import struct

import azure.functions as func
import requests
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import ManagedIdentityCredential, OnBehalfOfCredential

app = func.FunctionApp(
    http_auth_level=func.AuthLevel.ANONYMOUS
)  # Easy Auth does the auth

# The Function's user-assigned managed identity. It does two jobs:
#   1. It proves who the API is in the on-behalf-of exchange (a federated credential on the API's app
#      registration trusts it), so no client secret is needed. See _obo().
#   2. It is the identity the app-only tool reads the database as. See finance_list_cost_centres().
_managed_identity = ManagedIdentityCredential(
    client_id=os.environ.get("MANAGED_IDENTITY_CLIENT_ID")
)
TOKEN_EXCHANGE_AUDIENCE = "api://AzureADTokenExchange/.default"
SQL_SCOPE_DELEGATED = "https://database.windows.net/user_impersonation"
SQL_SCOPE_APP = "https://database.windows.net/.default"

SPEND_CATEGORIES = {"travel", "software", "training", "equipment"}
MAX_SPAN_DAYS = 366  # "at most 12 months"; the gateway enforces the same rule first


def _managed_identity_assertion() -> str:
    """A token from the managed identity, presented to Entra ID as the API's client credential."""
    return _managed_identity.get_token(TOKEN_EXCHANGE_AUDIENCE).token


def _claims(req: func.HttpRequest) -> dict[str, str]:
    """Claims of the validated caller, as decoded by Easy Auth."""
    raw = req.headers.get("X-MS-CLIENT-PRINCIPAL")
    if not raw:
        return {}
    principal = json.loads(base64.b64decode(raw))
    return {c["typ"]: c["val"] for c in principal.get("claims", [])}


def _json(body: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(body), status_code=status, mimetype="application/json"
    )


def _obo(req: func.HttpRequest, scope: str) -> str | func.HttpResponse:
    """Exchange the caller's token (audience = this API) for one to `scope`, still as the person.

    The API proves itself with its managed identity (a federated credential), or with a client secret
    when the deployment sets API_CLIENT_SECRET (obo_credential = "secret").
    Returns the downstream access token, or an error response to send back as-is.
    """
    auth = req.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return _json({"error": "no bearer token reached the function"}, 401)
    secret = os.environ.get("API_CLIENT_SECRET")
    credential = OnBehalfOfCredential(
        tenant_id=os.environ["TENANT_ID"],
        client_id=os.environ["API_CLIENT_ID"],
        user_assertion=auth[7:],
        **(
            {"client_secret": secret}
            if secret
            else {"client_assertion_func": _managed_identity_assertion}
        ),
    )
    try:
        return credential.get_token(scope).token
    except ClientAuthenticationError as e:
        return _json({"error": "obo_failed", "detail": e.message}, 502)


SQL_COPT_SS_ACCESS_TOKEN = 1256  # ODBC connection attribute for an Entra access token


def _sql_connect(token: str):
    """Open a connection to the finance database with an Entra access token."""
    # Imported here so a driver problem breaks only the database routes, not the whole app.
    import mssql_python

    raw = token.encode("utf-16-le")
    return mssql_python.connect(
        f"Server={os.environ['SQL_SERVER']};Database={os.environ['SQL_DATABASE']};"
        "Encrypt=yes;TrustServerCertificate=no;",
        attrs_before={
            SQL_COPT_SS_ACCESS_TOKEN: struct.pack(f"<I{len(raw)}s", len(raw), raw)
        },
    )


# ---- Directory ------------------------------------------------------------------------------------------


@app.route(route="directory/me", methods=["GET"])
def directory_get_my_profile(req: func.HttpRequest) -> func.HttpResponse:
    """Delegated: Graph returns what the person may see about themselves (User.Read)."""
    token = _obo(req, "https://graph.microsoft.com/User.Read")
    if isinstance(token, func.HttpResponse):
        return token
    graph = requests.get(
        "https://graph.microsoft.com/v1.0/me"
        "?$select=displayName,jobTitle,department,mail,userPrincipalName",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    return func.HttpResponse(
        graph.text, status_code=graph.status_code, mimetype="application/json"
    )


# ---- Finance --------------------------------------------------------------------------------------------


@app.route(route="finance/cost-centres", methods=["GET"])
def finance_list_cost_centres(req: func.HttpRequest) -> func.HttpResponse:
    """App-only: read reference data as this Function's own identity, not as the caller.

    The gateway has already checked that the person holds the CostCentres.Read app role. The database
    can't tell people apart here, so that check and the narrow database permission (SELECT on one view)
    are the controls. See docs/architecture.md.
    """
    claims = _claims(req)
    try:
        conn = _sql_connect(_managed_identity.get_token(SQL_SCOPE_APP).token)
    except Exception as e:  # noqa: BLE001 - report why, instead of an opaque 500
        return _json({"error": "app_only_connect_failed", "detail": str(e)[:300]}, 502)
    try:
        cursor = conn.cursor()
        # Who the database thinks is connected: proves the session runs as the service, not the person.
        cursor.execute("SELECT SUSER_SNAME(), USER_NAME()")
        queried_as, database_user = cursor.fetchone()
        cursor.execute(
            "SELECT code, name, department FROM finance.v_cost_centres ORDER BY code"
        )
        rows = [
            {"code": code, "name": name, "department": department}
            for code, name, department in cursor.fetchall()
        ]
    except Exception as e:  # noqa: BLE001 - e.g. the identity has no database user yet
        return _json({"error": "app_only_query_failed", "detail": str(e)[:300]}, 502)
    finally:
        conn.close()
    return _json(
        {
            "queried_as": queried_as,
            "database_user": database_user,
            "requested_by": claims.get("name", "unknown"),
            "cost_centres": rows,
        }
    )


def _spend_parameters(
    req: func.HttpRequest,
) -> tuple[str, dt.date, dt.date] | func.HttpResponse:
    """Validate the parameters again (the gateway already did): never trust what arrives."""
    category = (req.params.get("category") or "all").lower()
    if category != "all" and category not in SPEND_CATEGORIES:
        return _json(
            {
                "error": "invalid_category",
                "allowed": sorted(SPEND_CATEGORIES | {"all"}),
            },
            400,
        )
    try:
        start = dt.date.fromisoformat(req.params["from"])
        end = dt.date.fromisoformat(req.params["to"])
    except (KeyError, ValueError):
        return _json(
            {
                "error": "invalid_dates",
                "detail": "from and to are required, as YYYY-MM-DD",
            },
            400,
        )
    if end < start or (end - start).days > MAX_SPAN_DAYS:
        return _json(
            {
                "error": "invalid_range",
                "detail": "to must be on or after from, within 12 months",
            },
            400,
        )
    return category, start, end


@app.route(route="finance/spend", methods=["GET"])
def finance_query_spend(req: func.HttpRequest) -> func.HttpResponse:
    """Delegated: total spending by category, queried as the person.

    The model never writes SQL: it supplies typed parameters, and this runs one fixed, parameterised
    statement against one view. The database decides access: it grants SELECT on the view to the
    Finance Readers group, so anyone outside it is refused by the database itself.
    """
    params = _spend_parameters(req)
    if isinstance(params, func.HttpResponse):
        return params
    category, start, end = params

    token = _obo(req, SQL_SCOPE_DELEGATED)
    if isinstance(token, func.HttpResponse):
        return token
    try:
        conn = _sql_connect(token)
    except Exception as e:  # noqa: BLE001 - typically: this person has no database access at all
        return _json({"error": "database_refused", "detail": str(e)[:300]}, 403)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT SUSER_SNAME()")
        (queried_as,) = cursor.fetchone()
        cursor.execute(
            """SELECT category, SUM(amount_aud), COUNT(*)
                 FROM finance.v_spend
                WHERE spent_on BETWEEN ? AND ?
                  AND (? = 'all' OR category = ?)
                GROUP BY category
                ORDER BY category""",
            start,
            end,
            category,
            category,
        )
        totals = [
            {"category": cat, "amount_aud": float(amount), "transactions": count}
            for cat, amount, count in cursor.fetchall()
        ]
    except Exception as e:  # noqa: BLE001 - e.g. not in Finance Readers: SELECT permission denied
        return _json({"error": "database_refused", "detail": str(e)[:300]}, 403)
    finally:
        conn.close()
    return _json(
        {
            "queried_as": queried_as,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "totals": totals,
        }
    )


# ---- Diagnostics (not an MCP tool) ---------------------------------------------------------------------


@app.route(route="diagnostics/caller", methods=["GET"])
def diagnostics_caller(req: func.HttpRequest) -> func.HttpResponse:
    """Who is calling, from the token alone. The smoke test uses it; agents aren't offered it."""
    claims = _claims(req)
    return _json(
        {"user": claims.get("name", "unknown"), "calling_app": claims.get("azp")}
    )

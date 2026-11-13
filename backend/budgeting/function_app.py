"""Contoso budgeting API: a plain REST API the gateway exposes as MCP tools.

A separate system from finance spending. Auth is handled before this code runs (gateway + Easy Auth).
Both tools use delegated access (on-behalf-of) to the budgeting database; Contoso Budget Editors is
the group the database trusts.
"""

import base64
import json
import os
import struct

import azure.functions as func
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import ManagedIdentityCredential, OnBehalfOfCredential

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

_managed_identity = ManagedIdentityCredential(
    client_id=os.environ.get("MANAGED_IDENTITY_CLIENT_ID")
)
TOKEN_EXCHANGE_AUDIENCE = "api://AzureADTokenExchange/.default"
SQL_SCOPE_DELEGATED = "https://database.windows.net/user_impersonation"

MAX_AMOUNT = 10_000_000
MIN_YEAR, MAX_YEAR = 2000, 2100


def _managed_identity_assertion() -> str:
    return _managed_identity.get_token(TOKEN_EXCHANGE_AUDIENCE).token


def _claims(req: func.HttpRequest) -> dict[str, str]:
    raw = req.headers.get("X-MS-CLIENT-PRINCIPAL")
    if not raw:
        return {}
    principal = json.loads(base64.b64decode(raw))
    return {c["typ"]: c["val"] for c in principal.get("claims", [])}


def _json(body: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(body, default=str), status_code=status, mimetype="application/json"
    )


def _obo(req: func.HttpRequest, scope: str) -> str | func.HttpResponse:
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


SQL_COPT_SS_ACCESS_TOKEN = 1256


def _sql_connect(token: str):
    import mssql_python

    raw = token.encode("utf-16-le")
    return mssql_python.connect(
        f"Server={os.environ['SQL_SERVER']};Database={os.environ['SQL_DATABASE']};"
        "Encrypt=yes;TrustServerCertificate=no;",
        attrs_before={
            SQL_COPT_SS_ACCESS_TOKEN: struct.pack(f"<I{len(raw)}s", len(raw), raw)
        },
    )


def _parse_year(raw: str | None) -> int | func.HttpResponse:
    try:
        year = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _json(
            {
                "error": "invalid_fiscal_year",
                "detail": "fiscal_year must be an integer",
            },
            400,
        )
    if year < MIN_YEAR or year > MAX_YEAR:
        return _json(
            {
                "error": "invalid_fiscal_year",
                "detail": f"fiscal_year must be between {MIN_YEAR} and {MAX_YEAR}",
            },
            400,
        )
    return year


def _parse_amount(raw: str | None) -> float | func.HttpResponse:
    try:
        amount = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _json(
            {"error": "invalid_amount", "detail": "amount_aud must be a number"},
            400,
        )
    if amount < 0 or amount > MAX_AMOUNT:
        return _json(
            {
                "error": "invalid_amount",
                "detail": f"amount_aud must be between 0 and {MAX_AMOUNT}",
            },
            400,
        )
    return amount


@app.route(route="forecasts", methods=["GET"])
def budgeting_get_forecast(req: func.HttpRequest) -> func.HttpResponse:
    """Delegated: list forecasts as the person; Budget Editors only."""
    cost_centre = (req.params.get("cost_centre") or "").strip()
    if not cost_centre:
        return _json(
            {"error": "invalid_cost_centre", "detail": "cost_centre is required"}, 400
        )
    year = _parse_year(req.params.get("fiscal_year"))
    if isinstance(year, func.HttpResponse):
        return year

    token = _obo(req, SQL_SCOPE_DELEGATED)
    if isinstance(token, func.HttpResponse):
        return token
    try:
        conn = _sql_connect(token)
    except Exception as e:  # noqa: BLE001
        return _json({"error": "database_refused", "detail": str(e)[:300]}, 403)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT SUSER_SNAME()")
        (queried_as,) = cursor.fetchone()
        cursor.execute(
            """SELECT f.cost_centre, c.name, f.fiscal_year, f.amount_aud, f.updated_at, f.updated_by
                 FROM budgeting.v_forecasts f
                 JOIN budgeting.cost_centres c ON c.code = f.cost_centre
                WHERE f.fiscal_year = ?
                  AND (? = 'all' OR f.cost_centre = ?)
                ORDER BY f.cost_centre""",
            year,
            cost_centre,
            cost_centre,
        )
        forecasts = [
            {
                "cost_centre": code,
                "name": name,
                "fiscal_year": fiscal_year,
                "amount_aud": float(amount),
                "updated_at": updated_at,
                "updated_by": updated_by,
            }
            for code, name, fiscal_year, amount, updated_at, updated_by in cursor.fetchall()
        ]
    except Exception as e:  # noqa: BLE001
        return _json({"error": "database_refused", "detail": str(e)[:300]}, 403)
    finally:
        conn.close()
    return _json(
        {"queried_as": queried_as, "fiscal_year": year, "forecasts": forecasts}
    )


@app.route(route="forecasts", methods=["PUT"])
def budgeting_update_cost_centre_forecast(req: func.HttpRequest) -> func.HttpResponse:
    """Delegated write: set one forecast as the person; Budget Editors only; no approval gate."""
    cost_centre = (req.params.get("cost_centre") or "").strip()
    if not cost_centre or cost_centre.lower() == "all":
        return _json(
            {
                "error": "invalid_cost_centre",
                "detail": "cost_centre must be a single code",
            },
            400,
        )
    year = _parse_year(req.params.get("fiscal_year"))
    if isinstance(year, func.HttpResponse):
        return year
    amount = _parse_amount(req.params.get("amount_aud"))
    if isinstance(amount, func.HttpResponse):
        return amount

    token = _obo(req, SQL_SCOPE_DELEGATED)
    if isinstance(token, func.HttpResponse):
        return token
    try:
        conn = _sql_connect(token)
    except Exception as e:  # noqa: BLE001
        return _json({"error": "database_refused", "detail": str(e)[:300]}, 403)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT SUSER_SNAME()")
        (queried_as,) = cursor.fetchone()
        cursor.execute(
            "SELECT 1 FROM budgeting.cost_centres WHERE code = ?", cost_centre
        )
        if cursor.fetchone() is None:
            return _json({"error": "unknown_cost_centre", "detail": cost_centre}, 404)
        cursor.execute(
            """SELECT amount_aud FROM budgeting.v_forecasts
                WHERE cost_centre = ? AND fiscal_year = ?""",
            cost_centre,
            year,
        )
        prior = cursor.fetchone()
        previous = float(prior[0]) if prior else None
        cursor.execute(
            "EXEC budgeting.set_forecast @cost_centre=?, @fiscal_year=?, @amount_aud=?",
            cost_centre,
            year,
            amount,
        )
        cursor.execute(
            """SELECT amount_aud, updated_at, updated_by FROM budgeting.v_forecasts
                WHERE cost_centre = ? AND fiscal_year = ?""",
            cost_centre,
            year,
        )
        new_amount, updated_at, updated_by = cursor.fetchone()
        conn.commit()
    except Exception as e:  # noqa: BLE001
        return _json({"error": "database_refused", "detail": str(e)[:300]}, 403)
    finally:
        conn.close()
    return _json(
        {
            "queried_as": queried_as,
            "cost_centre": cost_centre,
            "fiscal_year": year,
            "previous_amount_aud": previous,
            "amount_aud": float(new_amount),
            "updated_at": updated_at,
            "updated_by": updated_by,
        }
    )

"""Contoso directory API: a plain REST API that the gateway (API Management) exposes to Copilot Studio
agents as an MCP tool. The directory is Microsoft Graph, so this app holds no data of its own: it
exchanges the caller's token for a Graph token and returns the caller's own profile. See
docs/architecture.md.

Auth is handled before this code runs:
- The gateway validates the caller's Entra token and the agent's allow-list.
- Function App built-in auth (Easy Auth) validates the token again and rejects anything without one.
So every request that reaches this handler carries a valid token for the gateway API.

Tool:
- directory_get_my_profile   Microsoft Graph, as the person (delegated, on-behalf-of)
"""

import json
import os

import azure.functions as func
import requests
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import ManagedIdentityCredential, OnBehalfOfCredential

app = func.FunctionApp(
    http_auth_level=func.AuthLevel.ANONYMOUS
)  # Easy Auth does the auth

# The Function's user-assigned managed identity. It proves who the API is in the on-behalf-of exchange (a
# federated credential on the API's app registration trusts it), so no client secret is needed.
_managed_identity = ManagedIdentityCredential(
    client_id=os.environ.get("MANAGED_IDENTITY_CLIENT_ID")
)
TOKEN_EXCHANGE_AUDIENCE = "api://AzureADTokenExchange/.default"


def _managed_identity_assertion() -> str:
    """A token from the managed identity, presented to Entra ID as the API's client credential."""
    return _managed_identity.get_token(TOKEN_EXCHANGE_AUDIENCE).token


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


@app.route(route="me", methods=["GET"])
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

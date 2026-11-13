# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp==2.3.0", "msal==1.39.0", "httpx2==2.16.0"]
# ///
"""Smoke test: act as Contoso's agents, sign in as you, and check the pass criteria.

Plays the role Copilot Studio plays later: get a delegated token for the gateway API through each
agent's client app, then talk MCP to that agent's endpoint in API Management.

    scripts/vpn.sh up                          # secure profile: API Management is private
    uv run scripts/smoke.py                    # secure (the default)
    uv run scripts/smoke.py --profile rapid    # rapid: public endpoints, no VPN

Needs allow_test_sign_in = true for the run (the agent apps refuse public-client sign-in otherwise),
scripts/sql-setup.py (finance), and scripts/sql-setup-budgeting.py (budgeting).
"""

import asyncio
import base64
import datetime as dt
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx2
import msal
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from tf import PROFILE, outputs

out = outputs()
TENANT, API, AGENTS = out["tenant_id"], out["api_client_id"], out["agents"]
SCOPE = [f"api://{API}/Tools.Read"]
SERVERS = out["servers"]
SECURE = PROFILE == "secure"
EMPLOYEE, FINANCE = "employee-assistant", "finance-assistant"


def server_of(tool: str) -> str:
    """The one MCP server that lists a tool."""
    return next(s for s, cfg in SERVERS.items() if tool in cfg["tools"])


def url_for(agent: str, tool: str) -> str:
    """The URL of the server on which an agent reaches a tool."""
    return AGENTS[agent]["servers"][server_of(tool)]


async def tools_listed(agent: str, token: str) -> list[str]:
    """Every tool the agent sees, across all the MCP servers it uses."""
    seen: set[str] = set()
    for url in AGENTS[agent]["servers"].values():
        seen |= set(await mcp_call(url, token))
    return sorted(seen)


# REST facade: (APIM API path, operation URL path) for checks that skip the MCP server.
TOOL_ROUTES = {
    "directory_get_my_profile": ("tools", "directory/me"),
    "finance_list_cost_centres": ("tools", "finance/cost-centres"),
    "finance_query_spend": ("tools", "finance/spend"),
    "diagnostics_caller": ("tools", "diagnostics/caller"),
    "budgeting_get_forecast": ("budgeting", "forecasts"),
    "budgeting_update_cost_centre_forecast": ("budgeting", "forecasts"),
}

# Arguments for tools that need them.
_today = dt.date.today()
_year = _today.year
TOOL_ARGS = {
    "finance_query_spend": {
        "category": "travel",
        "from": (_today - dt.timedelta(days=90)).isoformat(),
        "to": _today.isoformat(),
    },
    "budgeting_get_forecast": {
        "cost_centre": "CC-1001",
        "fiscal_year": str(_year),
    },
    "budgeting_update_cost_centre_forecast": {
        "cost_centre": "CC-1001",
        "fiscal_year": str(_year),
        "amount_aud": "421000",
    },
}


def rest_url(op: str, args: dict | None = None) -> str:
    api_path, op_path = TOOL_ROUTES[op]
    query = f"?{urlencode(args)}" if args else ""
    return f"{out['gateway_url']}/{api_path}/{op_path}{query}"


# Token cache, so re-runs don't need fresh sign-ins (gitignored; delete to sign in again).
CACHE_FILE = Path(__file__).parent / ".msal_cache.json"
cache = msal.SerializableTokenCache()
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE) as f:
        cache.deserialize(f.read())


def sign_in(agent: str, fresh: bool = False) -> str:
    """Sign in as the user through this agent's client app: cached token, else browser.

    fresh=True skips the cached access token, so claims that changed since (an app role) show up."""
    app = msal.PublicClientApplication(
        AGENTS[agent]["client_id"],
        authority=f"https://login.microsoftonline.com/{TENANT}",
        token_cache=cache,
    )
    # The cache can hold several accounts (e.g. from an earlier deployment); use any that still works.
    result = next(
        (
            r
            for acct in app.get_accounts()
            if (r := app.acquire_token_silent(SCOPE, account=acct, force_refresh=fresh))
        ),
        None,
    )
    if not result:
        # Browser sign-in: reuses the browser's Microsoft session, so usually just a click.
        # Falls back to device code when there's no browser (e.g. over SSH).
        try:
            print(f"\n[{agent}] Signing in via your browser...", flush=True)
            result = app.acquire_token_interactive(SCOPE, timeout=180)
        except Exception as e:  # noqa: BLE001 - any browser failure -> device code
            print(
                f"[{agent}] Browser sign-in unavailable ({e}); using a device code.",
                flush=True,
            )
            flow = app.initiate_device_flow(scopes=SCOPE)
            print(f"[{agent}] {flow['message']}", flush=True)
            result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise SystemExit(f"[{agent}] sign-in failed: {result.get('error_description')}")
    if cache.has_state_changed:
        with open(
            os.open(CACHE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"
        ) as f:
            f.write(cache.serialize())
    return result["access_token"]


async def mcp_initialize_status(url: str, token: str) -> int:
    """HTTP status of a bare MCP initialize request (the MCP SDK hides it behind -32603)."""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "0"},
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx2.AsyncClient(timeout=60) as http:
        return (await http.post(url, json=body, headers=headers)).status_code


async def mcp_call(
    url: str, token: str, tool: str | None = None, args: dict | None = None
):
    """Connect to an MCP endpoint; return its tool names, or the text of one tool call."""
    async with (
        httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, timeout=60
        ) as http,
        streamable_http_client(url, http_client=http) as (read, write),
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if tool is None:
                return sorted(t.name for t in (await session.list_tools()).tools)
            result = await session.call_tool(
                tool, args if args is not None else TOOL_ARGS.get(tool, {})
            )
            return result.content[0].text if result.content else str(result)


def _jwt_claims(token: str) -> dict:
    """Decode a JWT's payload without verifying it (only to read who it's for)."""
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def _guest_home_email(upn: str) -> str | None:
    """Guest UPN someone_hotmail.com#EXT#@tenant -> home email someone@hotmail.com."""
    if "#EXT#" not in upn:
        return None
    local = upn.split("#EXT#")[0]
    user, _, domain = local.rpartition("_")
    return f"{user}@{domain}"


def resolve(url: str) -> str | None:
    try:
        return socket.gethostbyname(urlparse(url).hostname)
    except socket.gaierror:
        return None


async def main():
    results = []

    def check(name, ok, detail):
        results.append((name, ok, detail))

    def skip(name, why):
        results.append((name, None, why))

    # Secure: API Management's name exists only in private DNS, reachable over the VPN.
    gw_ip = resolve(out["gateway_url"])
    if SECURE:
        check(
            "0. gateway resolves to its private IP",
            gw_ip == out["apim_private_ip"],
            f"{urlparse(out['gateway_url']).hostname} -> {gw_ip}",
        )
        if gw_ip is None:
            raise SystemExit(
                "The gateway's name doesn't resolve: connect the VPN first (scripts/vpn.sh up)."
            )
    else:
        check(
            "0. gateway resolves (public)",
            gw_ip is not None,
            f"{urlparse(out['gateway_url']).hostname} -> {gw_ip}",
        )

    tokens = {agent: sign_in(agent) for agent in AGENTS}
    emp, fin = AGENTS[EMPLOYEE], AGENTS[FINANCE]

    # An agent sees the tools of the servers it uses, and only those: the union is its own tool list.
    tools = await tools_listed(EMPLOYEE, tokens[EMPLOYEE])
    check(
        "1. Employee Assistant sees only its tools",
        tools == sorted(emp["tools"]),
        tools,
    )
    tools = await tools_listed(FINANCE, tokens[FINANCE])
    check(
        "2. Finance Assistant sees its tools across its two servers",
        tools == sorted(fin["tools"]) and len(fin["servers"]) == 2,
        tools,
    )

    # Same token, two servers: the one it is configured for must accept it, the other must refuse.
    own = await mcp_initialize_status(emp["servers"]["directory"], tokens[EMPLOYEE])
    other = await mcp_initialize_status(fin["servers"]["finance"], tokens[EMPLOYEE])
    check(
        "3. Employee Assistant blocked from the Finance server",
        own == 200 and other in (401, 403),
        f"directory server {own}, finance server {other}",
    )

    me = await mcp_call(
        url_for(FINANCE, "directory_get_my_profile"),
        tokens[FINANCE],
        "directory_get_my_profile",
    )
    check(
        "4. directory_get_my_profile: Graph returns the person (OBO)",
        "userPrincipalName" in me,
        me[:160],
    )

    async with httpx2.AsyncClient(timeout=60) as http:
        r = await http.get(rest_url("diagnostics_caller"))
    check(
        "5. gateway rejects calls without a token", r.status_code == 401, r.status_code
    )

    # Delegated database access: the database must see the person, not the service.
    spend = await mcp_call(
        url_for(FINANCE, "finance_query_spend"), tokens[FINANCE], "finance_query_spend"
    )
    try:
        body = json.loads(spend)
        login = body["queried_as"].lower()
        upn = json.loads(me)["userPrincipalName"]
        claims = _jwt_claims(tokens[FINANCE])
        known = {upn, _guest_home_email(upn)} | {
            claims.get(k) for k in ("upn", "unique_name", "email", "preferred_username")
        }
        known = {k.lower() for k in known if k}
        # Guests show up in SQL as "<home idp>#<email>", e.g. live.com#someone@hotmail.com.
        ok = (login in known or login.split("#", 1)[-1] in known) and isinstance(
            body["totals"], list
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        ok = False
    check("6. finance_query_spend: the database sees the person (OBO)", ok, spend[:160])

    # Bypass 1: skip the MCP server and call the REST facade directly. The Employee Assistant may call
    # diagnostics (control: 200) but not the finance operations (must be refused).
    async with httpx2.AsyncClient(timeout=60) as http:
        auth = {"Authorization": f"Bearer {tokens[EMPLOYEE]}"}
        rest = {
            op: (
                await http.get(rest_url(op, TOOL_ARGS.get(op)), headers=auth)
            ).status_code
            for op in (
                "diagnostics_caller",
                "finance_query_spend",
                "finance_list_cost_centres",
            )
        }
    check(
        "7. REST facade enforces the Employee Assistant's tools",
        rest["diagnostics_caller"] == 200
        and rest["finance_query_spend"] in (401, 403)
        and rest["finance_list_cost_centres"] in (401, 403),
        rest,
    )

    # Bypass 2: skip the gateway and call the Function with a valid token.
    if SECURE:
        # On the VPN its name resolves to the private endpoint, which the NSG opens to APIM's subnet only.
        async with httpx2.AsyncClient(timeout=10) as http:
            try:
                direct = (
                    await http.get(
                        f"{out['function_url']}/diagnostics/caller", headers=auth
                    )
                ).status_code
            except httpx2.TransportError as e:  # unreachable is the goal
                direct = type(e).__name__
        check(
            "8. Function refuses direct calls (gateway only)",
            direct not in range(200, 300),
            f"{direct} via {resolve(out['function_url'])}",
        )
    else:
        skip(
            "8. Function refuses direct calls (gateway only)",
            "rapid profile: the backend is public by design; proven only on secure",
        )

    # App-only access: the same person, a different identity at the database.
    cc_text = await mcp_call(
        url_for(FINANCE, "finance_list_cost_centres"),
        tokens[FINANCE],
        "finance_list_cost_centres",
    )
    try:
        cc = json.loads(cc_text)
        ok = (
            bool(cc["cost_centres"])
            and cc["database_user"] == out["function_identity_name"]
            and cc["queried_as"] != json.loads(spend)["queried_as"]
        )
    except (ValueError, KeyError, TypeError):
        ok = False
    check(
        "9. finance_list_cost_centres: the database sees the service (app-only)",
        ok,
        cc_text[:160],
    )

    async with httpx2.AsyncClient(timeout=60) as http:
        r = await http.get(rest_url("finance_list_cost_centres"), headers=auth)
    check(
        "10. Employee Assistant refused the app-only tool",
        r.status_code in (401, 403),
        r.status_code,
    )

    # Secretless: with obo_credential = managed_identity there is no client secret anywhere.
    if out["obo_credential"] == "managed_identity":
        try:
            settings = json.loads(
                subprocess.check_output(
                    [
                        "az",
                        "functionapp",
                        "config",
                        "appsettings",
                        "list",
                        "-g",
                        out["resource_group"],
                        "-n",
                        out["function_name"],
                        "-o",
                        "json",
                    ],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
            )
            secrets = json.loads(
                subprocess.check_output(
                    [
                        "az",
                        "ad",
                        "app",
                        "credential",
                        "list",
                        "--id",
                        API,
                        "-o",
                        "json",
                    ],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
            )
            names = {s["name"] for s in settings}
            ok = "API_CLIENT_SECRET" not in names and not secrets
            detail = f"function has API_CLIENT_SECRET: {'API_CLIENT_SECRET' in names}; app secrets: {len(secrets)}"
        except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
            ok, detail = False, f"could not read: {e}"
        check("11. no client secret anywhere (managed identity)", ok, detail)

    # The parameterised query: the gateway rejects bad parameters before the backend sees them.
    async with httpx2.AsyncClient(timeout=60) as http:
        fin_auth = {"Authorization": f"Bearer {tokens[FINANCE]}"}
        too_long = await http.get(
            rest_url(
                "finance_query_spend",
                {"category": "all", "from": "2023-01-01", "to": _today.isoformat()},
            ),
            headers=fin_auth,
        )
        bad_category = await http.get(
            rest_url(
                "finance_query_spend",
                {**TOOL_ARGS["finance_query_spend"], "category": "salaries"},
            ),
            headers=fin_auth,
        )
    check(
        "12. gateway rejects bad query parameters (range, category)",
        too_long.status_code == 400
        and "gateway" in too_long.text
        and bad_category.status_code == 400,
        f"over 12 months: {too_long.status_code}; unknown category: {bad_category.status_code}",
    )

    # Budgeting system (separate API + database): delegated read and write as the person.
    got = await mcp_call(
        url_for(FINANCE, "budgeting_get_forecast"),
        tokens[FINANCE],
        "budgeting_get_forecast",
    )
    try:
        before = json.loads(got)
        ok = (
            before.get("fiscal_year") == _year
            and isinstance(before.get("forecasts"), list)
            and len(before["forecasts"]) == 1
            and before["forecasts"][0]["cost_centre"] == "CC-1001"
        )
        previous_amount = before["forecasts"][0]["amount_aud"] if ok else None
    except (ValueError, KeyError, TypeError, IndexError):
        ok, previous_amount = False, None
    check(
        "15. budgeting_get_forecast: the budgeting database sees the person",
        ok,
        got[:160],
    )

    new_amount = 421000.0 if previous_amount != 421000.0 else 422000.0
    updated = await mcp_call(
        url_for(FINANCE, "budgeting_update_cost_centre_forecast"),
        tokens[FINANCE],
        "budgeting_update_cost_centre_forecast",
        {
            "cost_centre": "CC-1001",
            "fiscal_year": str(_year),
            "amount_aud": str(int(new_amount)),
        },
    )
    try:
        body = json.loads(updated)
        login = body["queried_as"].lower()
        upn = json.loads(me)["userPrincipalName"]
        claims = _jwt_claims(tokens[FINANCE])
        known = {upn, _guest_home_email(upn)} | {
            claims.get(k) for k in ("upn", "unique_name", "email", "preferred_username")
        }
        known = {k.lower() for k in known if k}
        writer = body["updated_by"].lower()
        ok = (
            float(body["amount_aud"]) == new_amount
            and (login in known or login.split("#", 1)[-1] in known)
            and (writer in known or writer.split("#", 1)[-1] in known)
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        ok = False
    check(
        "16. budgeting_update_cost_centre_forecast: write as the person",
        ok,
        updated[:180],
    )

    async with httpx2.AsyncClient(timeout=60) as http:
        emp_auth = {"Authorization": f"Bearer {tokens[EMPLOYEE]}"}
        denied = await http.put(
            rest_url(
                "budgeting_update_cost_centre_forecast",
                TOOL_ARGS["budgeting_update_cost_centre_forecast"],
            ),
            headers=emp_auth,
        )
        bad_amount = await http.put(
            rest_url(
                "budgeting_update_cost_centre_forecast",
                {
                    "cost_centre": "CC-1001",
                    "fiscal_year": str(_year),
                    "amount_aud": "-1",
                },
            ),
            headers=fin_auth,
        )
    check(
        "17. Employee Assistant refused the budgeting write; gateway rejects bad amount",
        denied.status_code in (401, 403) and bad_amount.status_code == 400,
        f"employee: {denied.status_code}; bad amount: {bad_amount.status_code}",
    )

    # Servers follow domains, so each tool lives on exactly one server and every agent on a server
    # sees the same list; the allow-list, not the server, decides who may call what.
    listed = [t for cfg in SERVERS.values() for t in cfg["tools"]]
    check(
        "13. every tool is defined on exactly one server",
        len(listed) == len(set(listed)),
        {s: cfg["tools"] for s, cfg in SERVERS.items()},
    )
    for sname, srv in SERVERS.items():
        if len(srv["agents"]) < 2:
            continue
        seen_by = {
            ag: await mcp_call(AGENTS[ag]["servers"][sname], tokens[ag])
            for ag in srv["agents"]
        }
        check(
            f"14. all agents on the shared '{sname}' server see the same tools",
            all(v == sorted(srv["tools"]) for v in seen_by.values()),
            {ag: len(v) for ag, v in seen_by.items()},
        )

    print(f"\nprofile: {PROFILE}\n")
    for name, ok, detail in results:
        label = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        print(f"{label}  {name:58}  {detail}")
    ran = [ok for _, ok, _ in results if ok is not None]
    print(f"\n{sum(ran)}/{len(ran)} passed, {len(results) - len(ran)} skipped")
    raise SystemExit(0 if all(ran) else 1)


async def no_role_check():
    """--no-role: after the app role is removed, a FRESH token must be refused the app-only tool.

    Run after `terraform apply -var 'cost_centres_user_upns=[]'`. A token signed in before the change
    still carries the role until it expires, so this takes a new one (it may ask you to sign in)."""
    token = sign_in(FINANCE, fresh=True)
    claims = _jwt_claims(token)
    async with httpx2.AsyncClient(timeout=60) as http:
        r = await http.get(
            rest_url("finance_list_cost_centres"),
            headers={"Authorization": f"Bearer {token}"},
        )
    has_role = "CostCentres.Read" in claims.get("roles", [])
    ok = (not has_role) and r.status_code == 403
    print(
        f"{'PASS' if ok else 'FAIL'}  fresh token has the role: {has_role}; app-only tool status: {r.status_code}"
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(no_role_check() if "--no-role" in sys.argv else main())

# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp==2.3.0", "msal==1.39.0", "httpx2==2.16.0"]
# ///
"""One-off MCP client against the finance-assistant server (default profile: rapid).

Signs in as you through the Finance Assistant app (needs allow_test_sign_in=true),
then initialize → tools/list → tools/call for profile + forecast.

    uv run scripts/mcp-client-once.py
    uv run scripts/mcp-client-once.py --profile secure
    uv run scripts/mcp-client-once.py --fresh
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import sys
from pathlib import Path

import httpx2
import msal
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from tf import outputs

out = outputs()
TENANT = out["tenant_id"]
API = out["api_client_id"]
FIN = out["agents"]["finance-assistant"]
MCP_URL = FIN["servers"]["finance"]
SCOPE = [f"api://{API}/Tools.Read"]
CACHE_FILE = Path(__file__).parent / ".msal_cache.json"


def sign_in(fresh: bool = False) -> str:
    cache = msal.SerializableTokenCache()
    if CACHE_FILE.exists():
        cache.deserialize(CACHE_FILE.read_text())
    app = msal.PublicClientApplication(
        FIN["client_id"],
        authority=f"https://login.microsoftonline.com/{TENANT}",
        token_cache=cache,
    )
    result = next(
        (
            r
            for acct in app.get_accounts()
            if (r := app.acquire_token_silent(SCOPE, account=acct, force_refresh=fresh))
        ),
        None,
    )
    if not result:
        print("[finance-assistant] Signing in via browser...", flush=True)
        try:
            result = app.acquire_token_interactive(SCOPE, timeout=180)
        except Exception as e:  # noqa: BLE001
            print(f"Browser unavailable ({e}); device code.", flush=True)
            flow = app.initiate_device_flow(scopes=SCOPE)
            print(flow["message"], flush=True)
            result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise SystemExit(f"sign-in failed: {result.get('error_description')}")
    if cache.has_state_changed:
        with open(
            os.open(CACHE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"
        ) as f:
            f.write(cache.serialize())
    return result["access_token"]


async def run(token: str) -> None:
    today = dt.date.today()
    async with (
        httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, timeout=60
        ) as http,
        streamable_http_client(MCP_URL, http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        init = await session.initialize()
        info = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
        print("initialize:", getattr(info, "name", None) or init)
        tools = sorted(t.name for t in (await session.list_tools()).tools)
        print("tools/list:", json.dumps(tools, indent=2))

        calls = [
            (
                "budgeting_get_forecast",
                {"cost_centre": "CC-1001", "fiscal_year": str(today.year)},
            ),
        ]
        for name, args in calls:
            if name not in tools:
                print(f"skip {name} (not on server)")
                continue
            print(f"\ntools/call {name} {args}")
            result = await session.call_tool(name, args)
            text = result.content[0].text if result.content else str(result)
            print(text[:1500])


def main() -> None:
    print(f"MCP_URL={MCP_URL}")
    token = sign_in(fresh="--fresh" in sys.argv)
    asyncio.run(run(token))


if __name__ == "__main__":
    main()

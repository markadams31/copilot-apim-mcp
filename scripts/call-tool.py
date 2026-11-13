# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp==2.3.0", "msal==1.39.0", "httpx2==2.16.0"]
# ///
"""Call one tool through the MCP server that lists it, as you, reusing smoke.py's cached sign-in.

    uv run scripts/call-tool.py finance-assistant finance_list_cost_centres
    uv run scripts/call-tool.py finance-assistant finance_query_spend '{"category": "travel", "from": "2026-07-01", "to": "2026-11-01"}'
    uv run scripts/call-tool.py --profile rapid finance-assistant directory_get_my_profile --fresh

Prints the tool's text, or the error. Run `uv run scripts/smoke.py` once first, so there is a cached
sign-in; --fresh asks Microsoft Entra ID for a new access token (so changed claims, such as an app
role, show up) without a new browser sign-in.
"""

import asyncio
import json
import sys

from smoke import _jwt_claims, mcp_call, sign_in, url_for

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if len(args) not in (2, 3):
    sys.exit(__doc__)
agent, tool = args[:2]
tool_args = (
    json.loads(args[2]) if len(args) == 3 else None
)  # None: smoke.py's defaults for the tool
token = sign_in(agent, fresh="--fresh" in sys.argv)
roles = _jwt_claims(token).get("roles", [])
print(f"token roles: {roles}")
try:
    print(asyncio.run(mcp_call(url_for(agent, tool), token, tool, tool_args)))
except Exception as e:  # noqa: BLE001 - show whatever the server said
    print(f"ERROR {type(e).__name__}: {e}")
    sys.exit(1)

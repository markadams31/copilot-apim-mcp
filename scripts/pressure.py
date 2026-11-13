# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp==2.3.0", "msal==1.39.0", "httpx2==2.16.0"]
# ///
"""Pressure tests: try to break the authorization, identity and abuse controls, with every
expectation stated up front. Run after the smoke test passes (secure: over the VPN).

    uv run scripts/pressure.py [--profile rapid]

1. Authorization grid: every agent x every tool x every path (own MCP server, REST facade),
   generated from Terraform's agent map so it can't drift from the configuration.
2. Cross-server: each agent's token on every MCP server it doesn't use.
3. Forged and foreign tokens: tampered signature, unsigned ("alg": "none"), and a valid Entra token
   for a different audience (Azure Resource Manager, via the Azure CLI).
4. Load: concurrent MCP tool calls through the whole chain (gateway -> backend -> OBO -> Graph);
   latency and error rate.
5. Rate limit: a burst on one agent and user must hit 429 after the per-minute allowance.
"""

import asyncio
import base64
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

sys.path.insert(0, str(Path(__file__).parent))
from smoke import (
    AGENTS,
    SERVERS,
    TOOL_ARGS,
    mcp_initialize_status,
    out,
    rest_url,
    server_of,
    sign_in,
)

GATEWAY = out["gateway_url"]
RATE_LIMIT = 30  # calls per agent per user per minute (infra: rate_limit_per_minute)


async def mcp_tool(url: str, token: str, tool: str) -> tuple[bool, str]:
    """Call one tool through an MCP server. Returns (succeeded, short detail)."""
    try:
        async with (
            httpx2.AsyncClient(
                headers={"Authorization": f"Bearer {token}"}, timeout=60
            ) as http,
            streamable_http_client(url, http_client=http) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(tool, TOOL_ARGS.get(tool, {}))
            text = result.content[0].text if result.content else ""
            # APIM errors (401/403/429 from a policy) reach the agent as ordinary tool text, not as
            # an MCP error, so check for them explicitly.
            gateway_error = re.match(r'\s*\{\s*"statusCode":\s*[45]\d\d', text)
            ok = not result.is_error and not gateway_error
            return ok, text[:60].replace("\n", " ")
    except BaseException as e:  # noqa: BLE001 - MCP SDK wraps HTTP errors in exception groups
        while isinstance(e, BaseExceptionGroup) and e.exceptions:
            e = e.exceptions[0]
        return False, f"{type(e).__name__}: {str(e)[:50]}"


def tamper(token: str) -> str:
    head, body, sig = token.split(".")
    return f"{head}.{body}.{sig[:-4]}{'AAAA' if sig[-4:] != 'AAAA' else 'BBBB'}"


def unsigned(token: str) -> str:
    _, body, _ = token.split(".")
    head = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
    )
    return f"{head}.{body}."


async def main():
    tokens = {a: sign_in(a) for a in AGENTS}
    all_tools = sorted({t for a in AGENTS.values() for t in a["tools"]})
    failures = 0

    # A previous run's rate-limit burst may still be inside its window: wait it out, or the grid
    # would see 429s instead of the authorization decisions it's testing.
    async with httpx2.AsyncClient(timeout=60) as http:
        for agent in AGENTS:
            h = {"Authorization": f"Bearer {tokens[agent]}"}
            while (
                r := await http.get(f"{GATEWAY}/tools/diagnostics/caller", headers=h)
            ).status_code == 429:
                wait = int(r.headers.get("Retry-After", "30")) + 2
                print(
                    f"({agent} is still throttled from an earlier run; waiting {wait} s)"
                )
                await asyncio.sleep(wait)

    def report(title, rows, cols):
        nonlocal failures
        print(f"\n## {title}\n")
        print("| " + " | ".join(cols) + " | result |")
        print("|" + "---|" * (len(cols) + 1))
        for *cells, ok in rows:
            failures += not ok
            print(
                "| "
                + " | ".join(str(c) for c in cells)
                + f" | {'PASS' if ok else '**FAIL**'} |"
            )

    # 1. Authorization grid
    rows = []
    async with httpx2.AsyncClient(timeout=60) as http:
        for agent, cfg in AGENTS.items():
            for tool in all_tools:
                allowed = tool in cfg["tools"]
                server = server_of(
                    tool
                )  # the one server that lists the tool; an agent that doesn't use it is refused there
                ok_mcp, detail = await mcp_tool(
                    SERVERS[server]["mcp_url"], tokens[agent], tool
                )
                rows.append(
                    (
                        agent,
                        tool,
                        f"{server} MCP server",
                        "allow" if allowed else "deny",
                        detail,
                        ok_mcp == allowed,
                    )
                )
                # The REST facade serves the budgeting write as a PUT on the same path as the read.
                method = (
                    "PUT" if tool == "budgeting_update_cost_centre_forecast" else "GET"
                )
                r = await http.request(
                    method,
                    rest_url(tool, TOOL_ARGS.get(tool)),
                    headers={"Authorization": f"Bearer {tokens[agent]}"},
                )
                expect = 200 if allowed else 403
                rows.append(
                    (
                        agent,
                        tool,
                        "REST facade",
                        expect,
                        r.status_code,
                        r.status_code == expect,
                    )
                )
    report("1. Authorization grid", rows, ["agent", "tool", "path", "expected", "got"])

    # 2. Cross-agent: every agent's token on every server it doesn't use
    rows = []
    for agent, cfg in AGENTS.items():
        for sname, srv in SERVERS.items():
            if sname in cfg["servers"]:
                continue
            status = await mcp_initialize_status(srv["mcp_url"], tokens[agent])
            rows.append(
                (
                    agent,
                    f"the {sname} MCP server",
                    "401/403",
                    status,
                    status in (401, 403),
                )
            )
    report("2. Cross-server tokens", rows, ["token of", "sent to", "expected", "got"])

    # 3. Forged and foreign tokens on the REST facade
    arm = subprocess.check_output(
        ["az", "account", "get-access-token", "--query", "accessToken", "-o", "tsv"],
        text=True,
    ).strip()
    good = tokens[list(AGENTS)[-1]]
    cases = [
        ("valid token (control)", good, 200),
        ("tampered signature", tamper(good), 401),
        ('unsigned ("alg": "none")', unsigned(good), 401),
        ("valid Entra token for another API (ARM)", arm, 401),
        ("no token", None, 401),
    ]
    rows = []
    async with httpx2.AsyncClient(timeout=60) as http:
        for name, tok, expect in cases:
            h = {"Authorization": f"Bearer {tok}"} if tok else {}
            r = await http.get(f"{GATEWAY}/tools/diagnostics/caller", headers=h)
            rows.append((name, expect, r.status_code, r.status_code == expect))
    report("3. Forged and foreign tokens", rows, ["token", "expected", "got"])

    print("\n(waiting 65 s for the rate-limit window to reset)")
    await asyncio.sleep(65)

    # 4. Load through the whole chain: concurrent directory_get_my_profile calls (APIM -> backend -> OBO -> Graph)
    agent = next(
        a for a, c in AGENTS.items() if "directory_get_my_profile" in c["tools"]
    )
    n, conc = 20, 5
    sem, lat, oks = asyncio.Semaphore(conc), [], 0

    async def one():
        nonlocal oks
        async with sem:
            t = time.perf_counter()
            ok, _ = await mcp_tool(
                SERVERS[server_of("directory_get_my_profile")]["mcp_url"],
                tokens[agent],
                "directory_get_my_profile",
            )
            lat.append(time.perf_counter() - t)
            oks += ok

    t0 = time.perf_counter()
    await asyncio.gather(*(one() for _ in range(n)))
    wall = time.perf_counter() - t0
    lat.sort()
    p95 = lat[int(0.95 * (len(lat) - 1))]
    print(
        f"\n## 4. Load: {n} directory_get_my_profile calls, {conc} at a time, as {agent}\n"
    )
    print("| succeeded | p50 | p95 | max | wall time |\n|---|---|---|---|---|")
    print(
        f"| {oks}/{n} | {statistics.median(lat):.2f} s | {p95:.2f} s | {lat[-1]:.2f} s | {wall:.1f} s |"
    )
    failures += oks != n

    print("\n(waiting 65 s for the rate-limit window to reset)")
    await asyncio.sleep(65)

    # 5. Rate limit: burst on one agent+user; expect 200 up to the allowance, then 429
    codes, retry_after = [], None
    async with httpx2.AsyncClient(timeout=60) as http:
        for _ in range(RATE_LIMIT + 10):
            r = await http.get(
                f"{GATEWAY}/tools/diagnostics/caller",
                headers={"Authorization": f"Bearer {good}"},
            )
            codes.append(r.status_code)
            retry_after = retry_after or r.headers.get("Retry-After")
    first_429 = codes.index(429) + 1 if 429 in codes else None
    # API Management's throttling is distributed, so its count is approximate: the classic Developer tier
    # was exact, BasicV2 let 2 extra calls through. Allow a few, then everything after must be refused.
    tolerance = 5
    ok = (
        first_429 is not None
        and RATE_LIMIT + 1 <= first_429 <= RATE_LIMIT + 1 + tolerance
        and set(codes[first_429 - 1 :]) == {429}
    )
    report(
        "5. Rate limit",
        [
            (
                len(codes),
                RATE_LIMIT,
                first_429,
                retry_after,
                "".join("." if c == 200 else "X" if c == 429 else "?" for c in codes),
                ok,
            )
        ],
        [
            "calls sent",
            "allowance",
            "first 429 at call",
            "Retry-After",
            "pattern (. = 200, X = 429)",
        ],
    )

    print(
        f"\n{'All expectations met.' if not failures else f'{failures} expectation(s) failed.'}"
    )
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())

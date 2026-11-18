# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""Build one Swagger 2.0 file for a Power Platform custom connector over the gateway's REST APIs.

    uv run scripts/make-connector-openapi.py --profile rapid > connector.swagger.json

This is the plain-REST alternative to the MCP servers: the agent calls the directory, finance and
budgeting REST APIs through one custom connector, with no MCP server involved. Custom connectors take
Swagger 2.0, so the three OpenAPI 3 files in backend/ are merged and converted here. Each API's path
prefix is added (/directory, /finance, /budgeting) so one connector with the gateway as its host reaches
all of them. The diagnostics operation is left out: it isn't a tool.

The connector's sign-in (Microsoft Entra ID, a managed identity, the agent's client app) is configured in
Power Apps, not in this file. Note that the Microsoft Copilot harness refused this connector type, so use a
standard harness agent (docs/deploy.md, "Which harness").
"""

import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
APIS = {"directory": "directory", "finance": "finance", "budgeting": "budgeting"}
SKIP = {"diagnostics_caller"}


def gateway_host(profile: str) -> str:
    url = subprocess.check_output(
        [
            "terraform",
            f"-chdir={ROOT}/infra/profiles/{profile}",
            "output",
            "-raw",
            "gateway_url",
        ],
        text=True,
    )
    return url.removeprefix("https://").strip()


def param(p: dict) -> dict:
    s = p["schema"]
    out = {
        "name": p["name"],
        "in": p["in"],
        "required": p.get("required", False),
        "type": s["type"],
        "description": p.get("description", ""),
    }
    if "enum" in s:
        out["enum"] = s["enum"]
    return out


def main() -> None:
    profile = (
        sys.argv[sys.argv.index("--profile") + 1]
        if "--profile" in sys.argv
        else "rapid"
    )
    paths: dict = {}
    for api, prefix in APIS.items():
        spec = yaml.safe_load((ROOT / "backend" / api / "openapi.yaml").read_text())
        for path, methods in spec["paths"].items():
            for method, op in methods.items():
                if op["operationId"] in SKIP:
                    continue
                paths.setdefault(f"/{prefix}{path}", {})[method] = {
                    "operationId": op["operationId"],
                    "summary": op["summary"],
                    "description": " ".join(op["description"].split()),
                    "parameters": [param(p) for p in op.get("parameters", [])],
                    "responses": {
                        "200": {"description": "OK", "schema": {"type": "object"}}
                    },
                }
    doc = {
        "swagger": "2.0",
        "info": {
            "title": "Contoso internal systems (REST)",
            "description": "Contoso's directory, finance and budgeting REST APIs, through the agent tool gateway.",
            "version": "1.0",
        },
        "host": gateway_host(profile),
        "basePath": "/",
        "schemes": ["https"],
        "consumes": ["application/json"],
        "produces": ["application/json"],
        "paths": paths,
    }
    json.dump(doc, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()

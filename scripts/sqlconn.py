"""Shared helper for the SQL scripts: connect to a Contoso database as you.

Whoever ran Terraform is the SQL server's Entra admin, so this signs in with your Azure CLI token.
Secure profile: the database has only a private endpoint, so run over the VPN during a deploy window
(allow_vpn_to_backends = true). Rapid profile: add your IP to sql_firewall_ip_addresses instead.
"""

import struct
import subprocess

import mssql_python
from tf import output

SQL_COPT_SS_ACCESS_TOKEN = 1256


def connect(database: str | None = None):
    """Return an open connection, signed in as the Azure CLI user.

    database defaults to the finance database (sql_database output). Pass budgeting_sql_database for
    the budgeting system.
    """
    db = database if database is not None else output("sql_database")
    token = subprocess.check_output(
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://database.windows.net/",
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ],
        text=True,
    ).strip()
    raw = token.encode("utf-16-le")
    return mssql_python.connect(
        f"Server={output('sql_server')};Database={db};"
        "Encrypt=yes;TrustServerCertificate=no;",
        attrs_before={
            SQL_COPT_SS_ACCESS_TOKEN: struct.pack(f"<I{len(raw)}s", len(raw), raw)
        },
    )

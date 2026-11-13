# /// script
# requires-python = ">=3.12"
# dependencies = ["mssql-python==1.17.0"]
# ///
"""Create Contoso's finance data and grant the two kinds of access the tools demonstrate.

    uv run scripts/sql-setup.py [--profile rapid]                    # data + both grants (idempotent)
    uv run scripts/sql-setup.py [--profile rapid] --revoke-identity  # app-only tool loses access
    uv run scripts/sql-setup.py [--profile rapid] --revoke-readers   # delegated tool: database refuses

Creates schema `finance` with two tables (cost centres; about a year of seeded spending) and one view
per tool. Then:

- App-only (finance_list_cost_centres): a database user for the Function's managed identity, with
  SELECT on finance.v_cost_centres only. No person gets access to that view, which is the point: the
  tool reads as the service, and the gateway's app-role check is what decides who may use it.
- Delegated (finance_query_spend): a database user for the Finance Readers Entra group, with SELECT on
  finance.v_spend only. The tool queries as the person, so the database itself refuses anyone who
  isn't in the group. Membership changes take effect at the person's next sign-in.

Runs as you (the SQL server's Entra admin). Secure profile: over the VPN, in a deploy window
(allow_vpn_to_backends = true). Rapid profile: your IP in sql_firewall_ip_addresses.
"""

import datetime as dt
import random
import sys

from sqlconn import connect
from tf import output

identity = output("function_identity_name")
readers = output("finance_readers_group")
for name in (identity, readers):
    if "]" in name:
        sys.exit(f"invalid principal name: {name}")

COST_CENTRES = [
    ("CC-1001", "Platform engineering", "Technology"),
    ("CC-1002", "Customer support", "Operations"),
    ("CC-2001", "Brand and campaigns", "Marketing"),
    ("CC-2002", "Partner programmes", "Marketing"),
    ("CC-3001", "Payroll and benefits", "People"),
    ("CC-4001", "Facilities and travel", "Corporate services"),
]
# Typical monthly spend per category (AUD): the seed varies around these.
CATEGORY_SCALE = {"travel": 4200, "software": 6500, "training": 1800, "equipment": 3100}


def seed_rows(today: dt.date) -> list[tuple]:
    """About a year of plausible spending, the same every time (fixed random seed)."""
    rng = random.Random(42)
    rows = []
    for months_back in range(12, -1, -1):
        first = (today.replace(day=1) - dt.timedelta(days=months_back * 30)).replace(
            day=1
        )
        for code, _, _ in COST_CENTRES:
            for category, scale in CATEGORY_SCALE.items():
                for _ in range(rng.randint(0, 3)):
                    day = first + dt.timedelta(days=rng.randint(0, 27))
                    if day > today:
                        continue
                    rows.append(
                        (
                            day,
                            code,
                            category,
                            round(rng.uniform(0.2, 1.0) * scale / 2, 2),
                        )
                    )
    return rows


def has_principal(cur, name: str) -> bool:
    cur.execute("SELECT 1 FROM sys.database_principals WHERE name = ?", name)
    return cur.fetchone() is not None


def drop_principal(cur, name: str, what: str) -> None:
    if has_principal(cur, name):
        cur.execute(f"DROP USER [{name}]")
        print(f"dropped the database user for {what} ({name})")
    else:
        print(f"{what} ({name}) has no database user")


conn = connect()
try:
    cur = conn.cursor()

    if "--revoke-identity" in sys.argv or "--revoke-readers" in sys.argv:
        if "--revoke-identity" in sys.argv:
            drop_principal(cur, identity, "the Function's identity")
        if "--revoke-readers" in sys.argv:
            drop_principal(cur, readers, "the Finance Readers group")
        conn.commit()
        sys.exit(0)

    cur.execute("IF SCHEMA_ID('finance') IS NULL EXEC('CREATE SCHEMA finance')")
    cur.execute(
        """IF OBJECT_ID('finance.cost_centres') IS NULL
           CREATE TABLE finance.cost_centres (
               code       varchar(10)  NOT NULL PRIMARY KEY,
               name       nvarchar(80) NOT NULL,
               department nvarchar(60) NOT NULL)"""
    )
    cur.execute(
        """IF OBJECT_ID('finance.spend') IS NULL
           CREATE TABLE finance.spend (
               id          int IDENTITY PRIMARY KEY,
               spent_on    date          NOT NULL,
               cost_centre varchar(10)   NOT NULL REFERENCES finance.cost_centres (code),
               category    varchar(20)   NOT NULL,
               amount_aud  decimal(12,2) NOT NULL)"""
    )

    cur.execute("SELECT COUNT(*) FROM finance.cost_centres")
    if cur.fetchone()[0] == 0:
        for row in COST_CENTRES:
            cur.execute(
                "INSERT INTO finance.cost_centres (code, name, department) VALUES (?, ?, ?)",
                *row,
            )

    cur.execute("SELECT COUNT(*) FROM finance.spend")
    if cur.fetchone()[0] == 0:
        rows = seed_rows(dt.date.today())
        for start in range(
            0, len(rows), 200
        ):  # 4 parameters a row, well under SQL's 2,100 limit
            batch = rows[start : start + 200]
            values = ", ".join(["(?, ?, ?, ?)"] * len(batch))
            params = [v for row in batch for v in row]
            cur.execute(
                f"INSERT INTO finance.spend (spent_on, cost_centre, category, amount_aud) VALUES {values}",
                *params,
            )
        print(f"seeded {len(rows)} spend rows")

    # One view per tool. A view and its table share an owner, so SELECT on the view is enough: the
    # grantees get no permission on the tables themselves.
    cur.execute(
        """CREATE OR ALTER VIEW finance.v_cost_centres AS
           SELECT code, name, department FROM finance.cost_centres"""
    )
    cur.execute(
        """CREATE OR ALTER VIEW finance.v_spend AS
           SELECT spent_on, cost_centre, category, amount_aud FROM finance.spend"""
    )

    if not has_principal(cur, identity):
        cur.execute(f"CREATE USER [{identity}] FROM EXTERNAL PROVIDER")
    cur.execute(f"GRANT SELECT ON OBJECT::finance.v_cost_centres TO [{identity}]")

    if not has_principal(cur, readers):
        cur.execute(f"CREATE USER [{readers}] FROM EXTERNAL PROVIDER")
    cur.execute(f"GRANT SELECT ON OBJECT::finance.v_spend TO [{readers}]")

    conn.commit()
    print(
        f"finance data ready; {identity} may SELECT finance.v_cost_centres only;"
        f" {readers} may SELECT finance.v_spend only"
    )
finally:
    conn.close()

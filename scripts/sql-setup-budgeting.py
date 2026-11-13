# /// script
# requires-python = ">=3.12"
# dependencies = ["mssql-python==1.17.0"]
# ///
"""Create Contoso's budgeting data and grant Budget Editors access.

    uv run scripts/sql-setup-budgeting.py [--profile rapid]
    uv run scripts/sql-setup-budgeting.py [--profile rapid] --revoke-editors

A separate database from finance. Cost-centre codes are duplicated here on purpose (fragmented
systems). The Budget Editors Entra group gets SELECT on the forecast view and EXECUTE on the write
proc; nobody else has a database user.
"""

import datetime as dt
import sys

from sqlconn import connect
from tf import output

editors = output("budget_editors_group")
if "]" in editors:
    sys.exit(f"invalid principal name: {editors}")

# Same codes as finance's seed, owned independently by this system.
COST_CENTRES = [
    ("CC-1001", "Platform engineering"),
    ("CC-1002", "Customer support"),
    ("CC-2001", "Brand and campaigns"),
    ("CC-2002", "Partner programmes"),
    ("CC-3001", "Payroll and benefits"),
    ("CC-4001", "Facilities and travel"),
]
# Seed forecasts: rough annual totals in AUD.
SEED_AMOUNTS = {
    "CC-1001": 420_000,
    "CC-1002": 310_000,
    "CC-2001": 185_000,
    "CC-2002": 95_000,
    "CC-3001": 1_250_000,
    "CC-4001": 240_000,
}


def has_principal(cur, name: str) -> bool:
    cur.execute("SELECT 1 FROM sys.database_principals WHERE name = ?", name)
    return cur.fetchone() is not None


conn = connect(database=output("budgeting_sql_database"))
try:
    cur = conn.cursor()

    if "--revoke-editors" in sys.argv:
        if has_principal(cur, editors):
            cur.execute(f"DROP USER [{editors}]")
            print(f"dropped the database user for Budget Editors ({editors})")
        else:
            print(f"Budget Editors ({editors}) has no database user")
        conn.commit()
        sys.exit(0)

    cur.execute("IF SCHEMA_ID('budgeting') IS NULL EXEC('CREATE SCHEMA budgeting')")
    cur.execute(
        """IF OBJECT_ID('budgeting.cost_centres') IS NULL
           CREATE TABLE budgeting.cost_centres (
               code varchar(10)  NOT NULL PRIMARY KEY,
               name nvarchar(80) NOT NULL)"""
    )
    cur.execute(
        """IF OBJECT_ID('budgeting.forecasts') IS NULL
           CREATE TABLE budgeting.forecasts (
               cost_centre varchar(10)    NOT NULL REFERENCES budgeting.cost_centres (code),
               fiscal_year int            NOT NULL,
               amount_aud  decimal(12,2)  NOT NULL,
               updated_at  datetime2      NOT NULL,
               updated_by  nvarchar(256)  NOT NULL,
               PRIMARY KEY (cost_centre, fiscal_year))"""
    )

    cur.execute("SELECT COUNT(*) FROM budgeting.cost_centres")
    if cur.fetchone()[0] == 0:
        for code, name in COST_CENTRES:
            cur.execute(
                "INSERT INTO budgeting.cost_centres (code, name) VALUES (?, ?)",
                code,
                name,
            )

    year = dt.date.today().year
    cur.execute("SELECT COUNT(*) FROM budgeting.forecasts WHERE fiscal_year = ?", year)
    if cur.fetchone()[0] == 0:
        for code, amount in SEED_AMOUNTS.items():
            cur.execute(
                """INSERT INTO budgeting.forecasts
                   (cost_centre, fiscal_year, amount_aud, updated_at, updated_by)
                   VALUES (?, ?, ?, SYSUTCDATETIME(), N'seed')""",
                code,
                year,
                amount,
            )
        print(f"seeded {len(SEED_AMOUNTS)} forecasts for {year}")

    cur.execute(
        """CREATE OR ALTER VIEW budgeting.v_forecasts AS
           SELECT cost_centre, fiscal_year, amount_aud, updated_at, updated_by
             FROM budgeting.forecasts"""
    )

    # MERGE as the caller: updated_by is always SUSER_SNAME(), never a parameter from the model.
    cur.execute(
        """CREATE OR ALTER PROCEDURE budgeting.set_forecast
             @cost_centre varchar(10),
             @fiscal_year int,
             @amount_aud  decimal(12,2)
           AS
           BEGIN
             SET NOCOUNT ON;
             MERGE budgeting.forecasts AS t
             USING (SELECT @cost_centre AS cost_centre, @fiscal_year AS fiscal_year) AS s
                ON t.cost_centre = s.cost_centre AND t.fiscal_year = s.fiscal_year
              WHEN MATCHED THEN
                UPDATE SET amount_aud = @amount_aud,
                           updated_at = SYSUTCDATETIME(),
                           updated_by = SUSER_SNAME()
              WHEN NOT MATCHED THEN
                INSERT (cost_centre, fiscal_year, amount_aud, updated_at, updated_by)
                VALUES (@cost_centre, @fiscal_year, @amount_aud, SYSUTCDATETIME(), SUSER_SNAME());
           END"""
    )

    if not has_principal(cur, editors):
        cur.execute(f"CREATE USER [{editors}] FROM EXTERNAL PROVIDER")
    # View + reference table for reads; EXECUTE on the proc for writes (ownership chaining covers MERGE).
    cur.execute(f"GRANT SELECT ON OBJECT::budgeting.v_forecasts TO [{editors}]")
    cur.execute(f"GRANT SELECT ON OBJECT::budgeting.cost_centres TO [{editors}]")
    cur.execute(f"GRANT EXECUTE ON OBJECT::budgeting.set_forecast TO [{editors}]")

    conn.commit()
    print(
        f"budgeting data ready; {editors} may read forecasts and execute set_forecast"
    )
finally:
    conn.close()

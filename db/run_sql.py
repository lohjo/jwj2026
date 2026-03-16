"""
db/run_sql.py — Run SQL files against ClickHouse Cloud in order.

Replaces the clickhouse-client --queries-file workflow using the
clickhouse-connect Python driver (already in requirements.txt).

Usage (from repo root):
    python -m db.run_sql                         # runs all db/sql/*.sql in sorted order
    python -m db.run_sql db/sql/00_create_db.sql # runs a single file
"""

import glob
import sys
from pathlib import Path

import clickhouse_connect

from config import (
    CLICKHOUSE_HOST,
    CLICKHOUSE_PORT,
    CLICKHOUSE_USER,
    CLICKHOUSE_PASSWORD,
)


def get_client():
    """Return a ClickHouse Cloud client using credentials from config.py."""
    return clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        secure=True,
        connect_timeout=30,
        send_receive_timeout=60,
    )


def execute_sql_file(client, filepath: str) -> None:
    """Execute every statement in a SQL file (split on ';')."""
    text = Path(filepath).read_text(encoding="utf-8")

    # Strip comments and split on semicolons
    statements = []
    for raw in text.split(";"):
        # Remove full-line comments
        lines = [
            line for line in raw.splitlines()
            if not line.strip().startswith("--")
        ]
        stmt = "\n".join(lines).strip()
        if stmt:
            statements.append(stmt)

    for i, stmt in enumerate(statements, 1):
        first_line = stmt.split("\n")[0][:80]
        print(f"  [{i}/{len(statements)}] {first_line}...")
        try:
            client.command(stmt)
            print(f"           ✓ OK")
        except Exception as exc:
            print(f"           ✗ FAILED: {exc}", file=sys.stderr)
            raise


def main():
    # Determine which files to run
    if len(sys.argv) > 1:
        files = sys.argv[1:]
    else:
        sql_dir = Path(__file__).resolve().parent / "sql"
        files = sorted(glob.glob(str(sql_dir / "*.sql")))

    if not files:
        print("No SQL files found.", file=sys.stderr)
        sys.exit(1)

    print("Connecting to ClickHouse Cloud...")
    client = get_client()

    # Quick connectivity check
    result = client.command("SELECT 1")
    print(f"Connection OK (SELECT 1 = {result})\n")

    for filepath in files:
        print(f"▶ {filepath}")
        execute_sql_file(client, filepath)
        print()

    print("All SQL files executed successfully.")


if __name__ == "__main__":
    main()

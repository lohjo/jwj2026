"""
Run SQL files against ClickHouse Cloud in order.

Replaces the clickhouse-client --queries-file workflow using the
clickhouse-connect Python driver (already in requirements.txt).

Usage:
    python run_sql.py                       # runs all sql/*.sql in sorted order
    python run_sql.py sql/00_create_db.sql  # runs a single file
"""

import glob
import os
import sys
from pathlib import Path

import clickhouse_connect
"""Phase 0 — Verify ClickHouse Cloud connectivity."""
    

def get_client():
    return clickhouse_connect.get_client(
        host=os.getenv(
            "CLICKHOUSE_HOST",
            "e8vpdqdapz.asia-southeast1.gcp.clickhouse.cloud",
        ),
        port=int(os.getenv("CLICKHOUSE_PORT", 8443)),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", "Y1JF.jPt_rb8o"),
        secure=True,
        connect_timeout=30,   # increase from default 10s
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

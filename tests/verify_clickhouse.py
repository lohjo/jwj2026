"""verify_clickhouse.py

Run lightweight ClickHouse health checks without exposing credentials.

Checks:
1) Config presence
2) DNS resolution
3) TCP connectivity to host:port
4) SQL connectivity (SELECT 1)
5) Optional table existence check for detection_events
"""

from __future__ import annotations

import argparse
import socket
import sys

from config import (
	CLICKHOUSE_HOST,
	CLICKHOUSE_PORT,
	CLICKHOUSE_USER,
	CLICKHOUSE_PASSWORD,
	CLICKHOUSE_DB,
	CLICKHOUSE_CONNECT_TIMEOUT,
	CLICKHOUSE_SEND_RECEIVE_TIMEOUT,
	CLICKHOUSE_MAX_RETRIES,
)


def _check_config() -> tuple[bool, str]:
	if not CLICKHOUSE_HOST:
		return False, "CLICKHOUSE_HOST missing"
	if not CLICKHOUSE_PASSWORD:
		return False, "CLICKHOUSE_PASSWORD missing"
	return True, "ok"


def _check_dns(host: str) -> tuple[bool, str]:
	try:
		infos = socket.getaddrinfo(host, None)
		if not infos:
			return False, "no DNS records"
		return True, f"resolved ({len(infos)} records)"
	except Exception as e:
		return False, f"dns_failed: {e}"


def _check_tcp(host: str, port: int, timeout: float) -> tuple[bool, str]:
	try:
		with socket.create_connection((host, port), timeout=timeout):
			return True, "tcp_ok"
	except Exception as e:
		return False, f"tcp_failed: {e}"


def _query_check(check_table: bool) -> tuple[bool, str]:
	try:
		import clickhouse_connect

		client = clickhouse_connect.get_client(
			host=CLICKHOUSE_HOST,
			port=CLICKHOUSE_PORT,
			username=CLICKHOUSE_USER,
			password=CLICKHOUSE_PASSWORD,
			database=CLICKHOUSE_DB,
			secure=True,
			connect_timeout=CLICKHOUSE_CONNECT_TIMEOUT,
			send_receive_timeout=CLICKHOUSE_SEND_RECEIVE_TIMEOUT,
			query_retries=CLICKHOUSE_MAX_RETRIES,
		)

		version = client.query("SELECT version()")
		_ = version.result_rows

		if check_table:
			res = client.query(
				"SELECT count() FROM system.tables WHERE database = {db:String} AND name = 'detection_events'",
				parameters={"db": CLICKHOUSE_DB},
			)
			exists = int(res.result_rows[0][0]) > 0
			if not exists:
				return False, "sql_ok_but_table_missing:detection_events"

		return True, "sql_ok"
	except Exception as e:
		return False, f"sql_failed: {e}"


def main() -> int:
	parser = argparse.ArgumentParser(description="Verify ClickHouse connectivity")
	parser.add_argument(
		"--check-table",
		action="store_true",
		help="Also verify detection_events table exists",
	)
	args = parser.parse_args()

	checks = []

	ok, msg = _check_config()
	checks.append(("config", ok, msg))
	if ok:
		ok_dns, msg_dns = _check_dns(CLICKHOUSE_HOST)
		checks.append(("dns", ok_dns, msg_dns))

		ok_tcp, msg_tcp = _check_tcp(
			CLICKHOUSE_HOST,
			CLICKHOUSE_PORT,
			timeout=max(float(CLICKHOUSE_CONNECT_TIMEOUT), 3.0),
		)
		checks.append(("tcp", ok_tcp, msg_tcp))

		ok_sql, msg_sql = _query_check(args.check_table)
		checks.append(("sql", ok_sql, msg_sql))

	all_ok = True
	for name, passed, detail in checks:
		status = "PASS" if passed else "FAIL"
		print(f"[{status}] {name}: {detail}")
		if not passed:
			all_ok = False

	return 0 if all_ok else 1


if __name__ == "__main__":
	sys.exit(main())

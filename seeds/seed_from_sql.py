"""Seed database from a SQL file containing INSERT statements."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List

import pymysql

# Ensure the project root is on sys.path when running as a script.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings


def _read_sql_file(path: Path) -> str:
	content = path.read_text(encoding="utf-8")
	# Strip UTF-8 BOM if present.
	return content.lstrip("\ufeff")


def _split_sql_statements(sql: str) -> List[str]:
	statements: List[str] = []
	buf: List[str] = []
	in_single = False
	in_double = False
	in_backtick = False
	in_line_comment = False
	in_block_comment = False
	escape = False

	i = 0
	length = len(sql)
	while i < length:
		ch = sql[i]
		nxt = sql[i + 1] if i + 1 < length else ""

		if in_line_comment:
			if ch == "\n":
				in_line_comment = False
			i += 1
			continue

		if in_block_comment:
			if ch == "*" and nxt == "/":
				in_block_comment = False
				i += 2
				continue
			i += 1
			continue

		if not in_single and not in_double and not in_backtick:
			if ch == "-" and nxt == "-":
				in_line_comment = True
				i += 2
				continue
			if ch == "#":
				in_line_comment = True
				i += 1
				continue
			if ch == "/" and nxt == "*":
				in_block_comment = True
				i += 2
				continue

		if ch == "\\" and (in_single or in_double):
			buf.append(ch)
			if i + 1 < length:
				buf.append(sql[i + 1])
				i += 2
				continue

		if ch == "'" and not in_double and not in_backtick:
			in_single = not in_single
		elif ch == '"' and not in_single and not in_backtick:
			in_double = not in_double
		elif ch == "`" and not in_single and not in_double:
			in_backtick = not in_backtick

		if ch == ";" and not in_single and not in_double and not in_backtick:
			statement = "".join(buf).strip()
			if statement:
				statements.append(statement)
			buf = []
			i += 1
			continue

		buf.append(ch)
		i += 1

	tail = "".join(buf).strip()
	if tail:
		statements.append(tail)
	return statements


def _connect():
	return pymysql.connect(
		host=settings.DATABASE_HOST,
		user=settings.DATABASE_USER,
		password=settings.DATABASE_PASSWORD,
		database=settings.DATABASE_NAME,
		port=settings.DATABASE_PORT,
		charset="utf8mb4",
		autocommit=True,
		cursorclass=pymysql.cursors.Cursor,
	)


def run_seed(sql_path: Path) -> int:
	sql = _read_sql_file(sql_path)
	statements = _split_sql_statements(sql)

	if not statements:
		print("No SQL statements found.")
		return 0

	total = 0
	with _connect() as conn:
		with conn.cursor() as cursor:
			for stmt in statements:
				cursor.execute(stmt)
				total += 1

	print(f"Executed {total} statement(s).")
	return total


def main(argv: Iterable[str] | None = None) -> int:
	parser = argparse.ArgumentParser(
		description="Seed database from a SQL file containing INSERT statements",
	)
	parser.add_argument(
		"sql_file",
		type=Path,
		help="Path to the .sql file",
	)
	args = parser.parse_args(argv)

	sql_path = args.sql_file
	if not sql_path.is_file():
		print(f"SQL file not found: {sql_path}")
		return 1

	try:
		run_seed(sql_path)
	except Exception as exc:  # noqa: BLE001 - surface error for CLI use
		print(f"Seed failed: {exc}")
		return 1

	return 0


if __name__ == "__main__":
	raise SystemExit(main())

"""Seed database from SQL files containing INSERT statements (idempotent)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pymysql

# Ensure the project root is on sys.path when running as a script.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings

# Configure logging
logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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
	try:
		return pymysql.connect(
			host=settings.DATABASE_HOST,
			user=settings.DATABASE_USER,
			password=settings.DATABASE_PASSWORD,
			database=settings.DATABASE_NAME,
			port=settings.DATABASE_PORT,
			charset="utf8mb4",
			autocommit=False,
			cursorclass=pymysql.cursors.DictCursor,
		)
	except pymysql.MySQLError as e:
		logger.error(f"Failed to connect to database: {e}")
		raise


def table_has_data(conn: pymysql.Connection, table_name: str) -> bool:
	"""Check if a table already has data."""
	try:
		with conn.cursor() as cursor:
			cursor.execute(f"SELECT COUNT(*) as count FROM `{table_name}` LIMIT 1")
			result = cursor.fetchone()
			return result and result.get('count', 0) > 0
	except pymysql.MySQLError as e:
		logger.warning(f"Error checking table {table_name}: {e}")
		return False


def run_seed(sql_path: Path, conn: Optional[pymysql.Connection] = None) -> bool:
	"""Execute a single SQL file."""
	if not sql_path.exists():
		logger.warning(f"SQL file not found: {sql_path}")
		return False
	
	try:
		sql = _read_sql_file(sql_path)
		statements = _split_sql_statements(sql)

		if not statements:
			logger.warning(f"No SQL statements found in {sql_path.name}")
			return False

		# If no connection provided, create one for this operation
		close_conn = False
		if conn is None:
			conn = _connect()
			close_conn = True

		try:
			logger.info(f"→ Executing seed file: {sql_path.name}")
			with conn.cursor() as cursor:
				for i, stmt in enumerate(statements, 1):
					if stmt.strip():
						cursor.execute(stmt)
			conn.commit()
			logger.info(f"✓ Successfully executed {sql_path.name} ({len(statements)} statements)")
			return True
		finally:
			if close_conn:
				conn.close()

	except Exception as exc:
		logger.error(f"✗ Seed failed for {sql_path.name}: {exc}")
		if conn:
			conn.rollback()
		return False


def run_seeds_idempotent(seeds: List[Tuple[Path, str]]) -> bool:
	"""Execute multiple seeds idempotently (skip if table has data)."""
	logger.info("=" * 60)
	logger.info("Starting idempotent database seeding...")
	logger.info("=" * 60)
	
	conn = None
	try:
		conn = _connect()
		logger.info("✓ Connected to database")
		
		executed_count = 0
		skipped_count = 0
		
		for seed_file, check_table in seeds:
			if table_has_data(conn, check_table):
				logger.info(f"✓ Table '{check_table}' already has data, skipping {seed_file.name}")
				skipped_count += 1
			else:
				if run_seed(seed_file, conn):
					executed_count += 1
				else:
					return False
		
		logger.info("=" * 60)
		logger.info(f"Seeding complete: {executed_count} executed, {skipped_count} skipped")
		logger.info("=" * 60)
		return True
		
	except Exception as e:
		logger.error(f"Fatal error during seeding: {e}")
		return False
	finally:
		if conn:
			conn.close()


def main(argv: Iterable[str] | None = None) -> int:
	parser = argparse.ArgumentParser(
		description="Seed database from SQL files (idempotent)",
	)
	parser.add_argument(
		"sql_file",
		nargs="?",
		type=Path,
		help="Path to the .sql file (optional, runs all seeds if not provided)",
	)
	args = parser.parse_args(argv)

	# If a specific file is provided, execute it
	if args.sql_file:
		sql_path = args.sql_file
		if not sql_path.is_file():
			logger.error(f"SQL file not found: {sql_path}")
			return 1
		
		try:
			success = run_seed(sql_path)
			return 0 if success else 1
		except Exception as exc:
			logger.error(f"Seed failed: {exc}")
			return 1
	
	# Otherwise, run all seeds idempotently
	seeds_dir = Path(__file__).parent
	seeds = [
		(seeds_dir / 'basic_data.sql', 'cms_content_types'),
		(seeds_dir / 'calculation_data.sql', 'main_calculations'),
	]
	
	try:
		success = run_seeds_idempotent(seeds)
		return 0 if success else 1
	except Exception as exc:
		logger.error(f"Seeding failed: {exc}")
		return 1


if __name__ == "__main__":
	raise SystemExit(main())

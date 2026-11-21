"""Reporting and CSV export for leads, DNC, and enrichment."""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

VALID_TABLES = {"leads", "dnc", "lead_enrichment"}


def export_table_to_csv(conn: sqlite3.Connection, table: str, output_path: Path | str) -> int:
    """Export a database table to CSV."""
    table = table.strip().lower()
    if table not in VALID_TABLES:
        raise ValueError(f"Unknown table '{table}'. Valid tables: {', '.join(sorted(VALID_TABLES))}")

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    cursor = conn.execute(f"SELECT * FROM {table}")
    headers = [d[0] for d in cursor.description]

    rows = cursor.fetchall()
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(list(row))

    return len(rows)


def get_lead_stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Return a dictionary mapping lead status to count."""
    rows = conn.execute("SELECT status, COUNT(*) AS count FROM leads GROUP BY status").fetchall()
    return {r["status"]: r["count"] for r in rows}

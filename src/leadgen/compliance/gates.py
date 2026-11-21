from __future__ import annotations

import sqlite3

from leadgen.phone import to_e164


def is_dnc(conn: sqlite3.Connection, phone_e164: str | None) -> bool:
    """Check whether a phone number is on the internal Do Not Call list."""
    if not phone_e164:
        return False
    norm = to_e164(phone_e164)
    candidates = {phone_e164}
    if norm:
        candidates.add(norm)
        if norm.startswith("+1") and len(norm) == 12:
            candidates.add(norm[2:])   # 10-digit national without country code
            candidates.add(norm[1:])   # 11-digit national with leading 1
    placeholders = ", ".join("?" for _ in candidates)
    row = conn.execute(f"SELECT 1 FROM dnc WHERE phone_e164 IN ({placeholders})", tuple(candidates)).fetchone()
    return row is not None


def add_dnc(conn: sqlite3.Connection, phone_e164: str, reason: str = "opt-out") -> None:
    """Add a phone number to the internal Do Not Call list."""
    norm = to_e164(phone_e164) or phone_e164
    conn.execute("INSERT OR IGNORE INTO dnc (phone_e164, reason) VALUES (?, ?)", (norm, reason))
    conn.commit()

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT,
    name TEXT NOT NULL,
    category TEXT,
    phone_e164 TEXT,
    address TEXT,
    city TEXT,
    state TEXT,
    lat REAL,
    lng REAL,
    timezone TEXT,
    website_uri TEXT,
    website_checked INTEGER NOT NULL DEFAULT 0,
    rating REAL,
    rating_count INTEGER,
    business_status TEXT,
    hours_json TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    attempts INTEGER NOT NULL DEFAULT 0,
    callback_at TEXT,
    notes TEXT,
    raw_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone_e164);

CREATE TABLE IF NOT EXISTS dnc (
    phone_e164 TEXT PRIMARY KEY,
    reason TEXT,
    added_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lead_enrichment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL UNIQUE REFERENCES leads(id),
    place_id TEXT,
    rating REAL,
    review_count INTEGER,
    top_reviews_json TEXT,
    categories_json TEXT,
    photo_refs_json TEXT,
    website_confirmed_none INTEGER NOT NULL DEFAULT 1,
    owner_notes TEXT,
    data_richness REAL NOT NULL DEFAULT 0.0,
    raw_json TEXT,
    fetched_at TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_enrichment_lead ON lead_enrichment(lead_id);
"""

# Keep LEAD_STATUSES column-for-column / status-for-status identical for cross-system contract.
# Leadgen itself only writes: new / verified / ready / disqualified / dnc.
LEAD_STATUSES = (
    "new", "verified", "ready", "calling", "yes", "no", "callback", "dnc", "disqualified", "voicemail",
)


def connect(path: str | Path = "data/leads.db") -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def insert_lead(conn: sqlite3.Connection, **fields) -> int | None:
    """Insert a lead; returns new id, or None if (source, source_id) already exists."""
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    cur = conn.execute(f"INSERT OR IGNORE INTO leads ({cols}) VALUES ({marks})", tuple(fields.values()))
    conn.commit()
    return cur.lastrowid if cur.rowcount else None


def get_lead(conn: sqlite3.Connection, lead_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()


def phone_in_leads(conn: sqlite3.Connection, phone: str | None) -> bool:
    """Check if a phone number already exists in the leads table across common formats."""
    if not phone:
        return False
    from leadgen.phone import to_e164

    norm = to_e164(phone)
    candidates = {phone}
    if norm:
        candidates.add(norm)
        if norm.startswith("+1") and len(norm) == 12:
            candidates.add(norm[2:])  # 10 digits
            candidates.add(norm[1:])  # 11 digits
    placeholders = ", ".join("?" for _ in candidates)
    row = conn.execute(
        f"SELECT 1 FROM leads WHERE phone_e164 IN ({placeholders}) LIMIT 1",
        tuple(candidates),
    ).fetchone()
    return row is not None


def save_enrichment(
    conn: sqlite3.Connection,
    lead_id: int,
    *,
    place_id: str | None = None,
    rating: float | None = None,
    review_count: int | None = None,
    top_reviews_json: str | None = None,
    categories_json: str | None = None,
    photo_refs_json: str | None = None,
    website_confirmed_none: bool = True,
    owner_notes: str | None = None,
    data_richness: float = 0.0,
    raw_json: str | None = None,
    fetched_at: str | None = None,
    expires_at: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO lead_enrichment (
            lead_id, place_id, rating, review_count, top_reviews_json, categories_json,
            photo_refs_json, website_confirmed_none, owner_notes, data_richness, raw_json,
            fetched_at, expires_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(lead_id) DO UPDATE SET
            place_id = coalesce(excluded.place_id, lead_enrichment.place_id),
            rating = coalesce(excluded.rating, lead_enrichment.rating),
            review_count = coalesce(excluded.review_count, lead_enrichment.review_count),
            top_reviews_json = coalesce(excluded.top_reviews_json, lead_enrichment.top_reviews_json),
            categories_json = coalesce(excluded.categories_json, lead_enrichment.categories_json),
            photo_refs_json = coalesce(excluded.photo_refs_json, lead_enrichment.photo_refs_json),
            website_confirmed_none = excluded.website_confirmed_none,
            owner_notes = coalesce(excluded.owner_notes, lead_enrichment.owner_notes),
            data_richness = excluded.data_richness,
            raw_json = coalesce(excluded.raw_json, lead_enrichment.raw_json),
            fetched_at = coalesce(excluded.fetched_at, lead_enrichment.fetched_at),
            expires_at = coalesce(excluded.expires_at, lead_enrichment.expires_at),
            updated_at = datetime('now')
        """,
        (
            lead_id,
            place_id,
            rating,
            review_count,
            top_reviews_json,
            categories_json,
            photo_refs_json,
            1 if website_confirmed_none else 0,
            owner_notes,
            data_richness,
            raw_json,
            fetched_at,
            expires_at,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM lead_enrichment WHERE lead_id = ?", (lead_id,)).fetchone()
    return row[0] if row else cur.lastrowid


def get_enrichment(conn: sqlite3.Connection, lead_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM lead_enrichment WHERE lead_id = ?", (lead_id,)).fetchone()


def purge_expired_enrichment(conn: sqlite3.Connection, now_iso: str | None = None) -> int:
    """Delete expiring fields (reviews, photos, raw_json) from expired enrichment rows.
    
    Keeps place_id, data_richness, rating, review_count, categories, and timestamps.
    """
    if now_iso:
        cur = conn.execute(
            """
            UPDATE lead_enrichment
            SET top_reviews_json = NULL,
                photo_refs_json = NULL,
                raw_json = NULL,
                updated_at = datetime('now')
            WHERE expires_at IS NOT NULL
              AND expires_at < ?
              AND (top_reviews_json IS NOT NULL OR photo_refs_json IS NOT NULL OR raw_json IS NOT NULL)
            """,
            (now_iso,),
        )
    else:
        cur = conn.execute(
            """
            UPDATE lead_enrichment
            SET top_reviews_json = NULL,
                photo_refs_json = NULL,
                raw_json = NULL,
                updated_at = datetime('now')
            WHERE expires_at IS NOT NULL
              AND expires_at < datetime('now')
              AND (top_reviews_json IS NOT NULL OR photo_refs_json IS NOT NULL OR raw_json IS NOT NULL)
            """
        )
    conn.commit()
    return cur.rowcount

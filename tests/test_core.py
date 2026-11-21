import os
import sqlite3
from datetime import time
from pathlib import Path

import pytest

from leadgen.config import Settings, _bool, _time, get_settings
from leadgen.db import connect, get_lead, init_db, insert_lead, phone_in_leads
from leadgen.phone import pretty_us, to_e164


# --- Config Tests ---

@pytest.mark.parametrize("val,expected", [
    ("1", True),
    ("true", True),
    ("True", True),
    ("TRUE", True),
    ("yes", True),
    ("YES", True),
    ("on", True),
    ("ON", True),
    ("0", False),
    ("false", False),
    ("False", False),
    ("no", False),
    ("off", False),
    ("", False),
    ("anything_else", False),
])
def test_config_bool_parser(monkeypatch, val, expected):
    monkeypatch.setenv("TEST_FLAG", val)
    assert _bool("TEST_FLAG") == expected


def test_config_bool_default():
    assert _bool("NON_EXISTENT_VAR", default=True) is True
    assert _bool("NON_EXISTENT_VAR", default=False) is False


@pytest.mark.parametrize("val,expected_time", [
    ("08:00", time(8, 0)),
    ("8:30", time(8, 30)),
    ("21:00", time(21, 0)),
    ("0:00", time(0, 0)),
    ("23:59", time(23, 59)),
])
def test_config_time_parser(monkeypatch, val, expected_time):
    monkeypatch.setenv("TEST_TIME", val)
    assert _time("TEST_TIME", "12:00") == expected_time


def test_settings_frozen():
    s = Settings()
    with pytest.raises(Exception):
        s.places_api_key = "new_key"  # type: ignore


def test_settings_custom_overrides():
    s = Settings(
        places_api_key="custom_places",
        geoapify_api_key="custom_geo",
        enrichment_ttl_days=14,
    )
    assert s.places_api_key == "custom_places"
    assert s.geoapify_api_key == "custom_geo"
    assert s.enrichment_ttl_days == 14


def test_get_settings():
    s = get_settings()
    assert isinstance(s, Settings)
    assert s.enrichment_ttl_days == 7


# --- DB Tests ---

def test_db_init_and_tables(tmp_path):
    db_file = tmp_path / "subdir" / "test.db"
    conn = connect(db_file)
    init_db(conn)

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"leads", "dnc", "lead_enrichment"}.issubset(tables)


def test_db_foreign_keys_enabled():
    conn = connect(":memory:")
    init_db(conn)

    fk_status = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk_status == 1

    # Inserting enrichment with non-existent lead_id must raise an IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO lead_enrichment (lead_id) VALUES (99999)")


def test_insert_and_get_lead():
    conn = connect(":memory:")
    init_db(conn)

    lid = insert_lead(
        conn,
        source="osm",
        source_id="node_123",
        name="Baker's Delight",
        phone_e164="+15125550199",
        city="Austin",
        state="TX",
        status="new",
    )
    assert lid is not None

    lead = get_lead(conn, lid)
    assert lead is not None
    assert lead["name"] == "Baker's Delight"
    assert lead["phone_e164"] == "+15125550199"
    assert lead["status"] == "new"
    assert lead["attempts"] == 0


def test_insert_lead_duplicate_unique_constraint():
    conn = connect(":memory:")
    init_db(conn)

    lid1 = insert_lead(conn, source="osm", source_id="node_dup", name="Shop 1")
    assert lid1 is not None

    lid2 = insert_lead(conn, source="osm", source_id="node_dup", name="Shop 1 Duplicate")
    assert lid2 is None

    count = conn.execute("SELECT COUNT(*) FROM leads WHERE source_id = 'node_dup'").fetchone()[0]
    assert count == 1


# --- Phone Tests ---

def test_phone_normalization_and_formatting():
    assert to_e164("(512) 555-0199") == "+15125550199"
    assert to_e164("512-555-0199") == "+15125550199"
    assert to_e164("invalid") is None
    assert to_e164(None) is None

    assert pretty_us("+15125550199") == "(512) 555-0199"
    assert pretty_us("") == ""
    assert pretty_us(None) == ""


def test_phone_in_leads(tmp_path):
    conn = connect(":memory:")
    init_db(conn)

    insert_lead(conn, source="csv", source_id="c1", name="Plumber", phone_e164="+15125550123")
    assert phone_in_leads(conn, "(512) 555-0123") is True
    assert phone_in_leads(conn, "5125550123") is True
    assert phone_in_leads(conn, "+15125550123") is True
    assert phone_in_leads(conn, "+15125550999") is False

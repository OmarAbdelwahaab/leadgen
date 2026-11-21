"""Tests for facts assembly and export logic."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from leadgen.db import connect, init_db, insert_lead, save_enrichment
from leadgen.facts import (
    build_facts_dict,
    clean_address,
    export_all_ready_facts,
    export_facts_for_lead,
    parse_hours,
    slugify,
)


@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_facts.db"
    conn = connect(db_file)
    init_db(conn)
    return conn


@pytest.fixture
def ready_lead(test_db):
    lid = insert_lead(
        test_db,
        source="places",
        source_id="places/ChIJ123",
        name="Austin Auto Repair",
        category="auto repair",
        phone_e164="+15125550199",
        address="100 Congress Ave, Austin, TX 78701, United States",
        city="Austin",
        state="TX",
        lat=30.2672,
        lng=-97.7431,
        timezone="America/Chicago",
        website_uri="https://facebook.com/austinautorepair",
        hours_json=json.dumps(["Monday: 8:00 AM – 5:00 PM; Tuesday: 8:00 AM – 5:00 PM"]),
        rating=4.8,
        rating_count=32,
        status="ready",
    )
    return lid


def test_hours_parsing():
    # Google format
    g_hours = ["Monday: 8:00 AM – 5:00 PM", "Tuesday: 8:00 AM – 5:00 PM"]
    parsed_g = parse_hours(g_hours)
    assert len(parsed_g) == 2
    assert parsed_g[0].day == "Monday"
    assert "8:00 AM" in parsed_g[0].text

    # OSM format
    osm_hours = ["Mo-Fr 08:00-17:00; Sa 09:00-13:00"]
    parsed_osm = parse_hours(osm_hours)
    assert len(parsed_osm) == 2
    assert parsed_osm[0].day == "Mon–Fri"
    assert parsed_osm[1].day == "Sat"

    # 24/7
    parsed_24 = parse_hours(["24/7"])
    assert len(parsed_24) == 1
    assert parsed_24[0].text == "Open 24/7"


def test_clean_address_and_slugify():
    assert clean_address("Austin Auto Repair, 100 Main St, USA", "Austin Auto Repair") == "100 Main St"
    assert clean_address("200 Elm St, United States of America") == "200 Elm St"
    assert slugify("Austin Auto Repair!") == "austin-auto-repair"


def test_build_facts_dict_schema_and_no_design(test_db, ready_lead):
    # Add active enrichment
    future_iso = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    save_enrichment(
        test_db,
        lead_id=ready_lead,
        place_id="places/ChIJ123",
        rating=4.9,
        review_count=35,
        top_reviews_json=json.dumps([{"author_name": "Bob", "text": "Quick and honest service", "rating": 5.0}]),
        categories_json=json.dumps(["auto repair", "brake shop"]),
        photo_refs_json=json.dumps([{"name": "places/123/photos/abc", "author_name": "Owner"}]),
        data_richness=0.85,
        fetched_at=now_iso,
        expires_at=future_iso,
    )

    facts = build_facts_dict(test_db, ready_lead)

    # Required factual fields
    assert facts["lead_id"] == ready_lead
    assert facts["name"] == "Austin Auto Repair"
    assert facts["category"] == "auto repair"
    assert facts["phone"]["display"] == "(512) 555-0199"
    assert facts["phone"]["e164"] == "+15125550199"
    assert facts["address"] == "100 Congress Ave, Austin, TX 78701"
    assert facts["city"] == "Austin"
    assert facts["state"] == "TX"
    assert facts["lat"] == 30.2672
    assert facts["lng"] == -97.7431
    assert facts["timezone"] == "America/Chicago"
    assert len(facts["hours"]) == 2
    assert facts["rating"] == 4.9
    assert facts["rating_count"] == 35
    assert facts["categories"] == ["auto repair", "brake shop"]
    assert facts["place_id"] == "places/ChIJ123"
    assert facts["website_status"]["status"] == "social_only"
    assert "facebook.com" in facts["website_status"]["links"][0]

    # Enrichment present because unexpired
    assert facts["enrichment"] is not None
    assert facts["enrichment"]["fetched_at"] == now_iso
    assert facts["enrichment"]["expires_at"] == future_iso
    assert len(facts["enrichment"]["review_snippets"]) == 1
    assert facts["enrichment"]["attribution"] == "Google Places API"

    # Sources provenance
    assert facts["sources"]["lead_source"] == "places"
    assert facts["sources"]["enrichment"] == "google_places"

    # Strict check: ABSOLUTELY NO DESIGN OR TEMPLATE-ERA KEYS
    forbidden_keys = {
        "theme", "design_constraints", "agency_credit", "tagline", "about",
        "services", "cta_label", "brief", "brief_markdown", "template", "palette",
    }
    present_forbidden = forbidden_keys.intersection(facts.keys())
    assert not present_forbidden, f"Design keys leaked into facts.json: {present_forbidden}"


def test_export_facts_for_lead(test_db, ready_lead, tmp_path: Path):
    packets_dir = tmp_path / "packets"
    path = export_facts_for_lead(test_db, ready_lead, base_dir=packets_dir)

    assert path.exists()
    assert path.name == "facts.json"
    assert path.parent.name == f"austin-auto-repair-{ready_lead}"

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["lead_id"] == ready_lead
    assert loaded["name"] == "Austin Auto Repair"


def test_export_facts_refuses_non_ready_leads(test_db, tmp_path: Path):
    non_ready_id = insert_lead(
        test_db,
        source="places",
        source_id="p_non_ready",
        name="Draft Shop",
        status="verified",
    )
    with pytest.raises(ValueError, match="Only ready leads can be exported"):
        export_facts_for_lead(test_db, non_ready_id, base_dir=tmp_path)


def test_export_facts_omits_expired_enrichment(test_db, ready_lead, tmp_path: Path):
    past_iso = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    save_enrichment(
        test_db,
        lead_id=ready_lead,
        place_id="places/ChIJ123",
        top_reviews_json=json.dumps([{"author_name": "Old", "text": "Old review"}]),
        photo_refs_json=json.dumps([{"name": "places/123/photo"}]),
        data_richness=0.85,
        expires_at=past_iso,
    )

    path = export_facts_for_lead(test_db, ready_lead, base_dir=tmp_path)
    loaded = json.loads(path.read_text(encoding="utf-8"))

    # Enrichment block must be omitted (None) because it is expired
    assert loaded["enrichment"] is None


def test_export_all_ready_facts(test_db, ready_lead, tmp_path: Path):
    # Add another ready lead
    lid2 = insert_lead(test_db, source="places", source_id="p2", name="Second Shop", status="ready")
    # Add a non-ready lead
    insert_lead(test_db, source="places", source_id="p3", name="Third Shop", status="disqualified")

    exported = export_all_ready_facts(test_db, base_dir=tmp_path)
    assert len(exported) == 2
    slugs = [p.parent.name for p in exported]
    assert any(f"-{ready_lead}" in s for s in slugs)
    assert any(f"-{lid2}" in s for s in slugs)

"""Unit tests for lead enrichment, Places details, and data richness scoring."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from leadgen.config import Settings
from leadgen.db import (
    connect,
    get_enrichment,
    get_lead,
    init_db,
    insert_lead,
    purge_expired_enrichment,
    save_enrichment,
)
from leadgen.enrichment import (
    LeadEnrichment,
    PhotoReference,
    ReviewSnippet,
    compute_data_richness,
    enrich_lead,
    fetch_place_details,
)


@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_enrichment.db"
    conn = connect(db_file)
    init_db(conn)
    return conn


@pytest.fixture
def ready_lead_id(test_db):
    lid = insert_lead(
        test_db,
        source="places",
        source_id="places/ChIJ12345678",
        name="Thistle Cafe",
        category="cafe",
        phone_e164="+15125550100",
        address="123 Main St, Austin, TX 78701",
        city="Austin",
        state="TX",
        lat=30.2672,
        lng=-97.7431,
        hours_json=json.dumps(["Mo-Fr 07:30-14:30; Sa 08:00-12:00"]),
        rating=4.5,
        rating_count=12,
        status="ready",
    )
    assert lid is not None
    return lid


def test_db_enrichment_crud(test_db, ready_lead_id):
    now_iso = datetime.now(timezone.utc).isoformat()
    expires_iso = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    eid = save_enrichment(
        test_db,
        lead_id=ready_lead_id,
        place_id="places/ChIJ12345678",
        rating=4.8,
        review_count=35,
        top_reviews_json=json.dumps([{"author_name": "Alice", "text": "Great latte", "rating": 5.0}]),
        categories_json=json.dumps(["coffee shop", "bakery"]),
        photo_refs_json=json.dumps([{"name": "places/foo/photos/bar", "author_name": "Bob"}]),
        website_confirmed_none=True,
        owner_notes="Family owned since 2015",
        data_richness=0.85,
        fetched_at=now_iso,
        expires_at=expires_iso,
    )
    assert eid is not None

    row = get_enrichment(test_db, ready_lead_id)
    assert row is not None
    assert row["lead_id"] == ready_lead_id
    assert row["place_id"] == "places/ChIJ12345678"
    assert row["rating"] == 4.8
    assert row["review_count"] == 35
    assert row["website_confirmed_none"] == 1
    assert row["data_richness"] == 0.85
    assert row["fetched_at"] == now_iso
    assert row["expires_at"] == expires_iso
    assert "Alice" in row["top_reviews_json"]


def test_data_richness_scoring(test_db, ready_lead_id):
    lead = get_lead(test_db, ready_lead_id)

    # Empty enrichment
    empty_enrich = LeadEnrichment(lead_id=ready_lead_id)
    score_empty = compute_data_richness(empty_enrich, lead=None)
    assert score_empty == 0.0

    # Lead with hours and category from DB
    score_basic = compute_data_richness(empty_enrich, lead=lead)
    # hours (0.20) + category (0.15) = 0.35
    assert score_basic == 0.35

    # Rich enrichment
    rich_enrich = LeadEnrichment(
        lead_id=ready_lead_id,
        rating=4.9,
        review_count=50,
        top_reviews=[
            ReviewSnippet(author_name="A", text="Love this place!"),
            ReviewSnippet(author_name="B", text="Amazing pastry selection."),
        ],
        categories=["coffee shop", "bakery"],
        photo_refs=[
            PhotoReference(name="places/1/photos/a"),
            PhotoReference(name="places/1/photos/b"),
        ],
        owner_notes="Signature cinnamon rolls sell out by 10am.",
    )
    score_rich = compute_data_richness(rich_enrich, lead=lead)
    # photos(0.25) + reviews(0.25) + hours(0.20) + categories(0.15) + notes(0.15) = 1.0
    assert score_rich == 1.0


def test_fetch_place_details_mock():
    mock_payload = {
        "id": "places/ChIJtest123",
        "displayName": {"text": "Austin Coffee Works"},
        "formattedAddress": "500 Congress Ave, Austin, TX 78701",
        "nationalPhoneNumber": "(512) 555-9876",
        "rating": 4.7,
        "userRatingCount": 88,
        "types": ["cafe", "point_of_interest", "establishment"],
        "primaryType": "coffee_shop",
        "websiteUri": None,
        "reviews": [
            {
                "authorAttribution": {"displayName": "Sarah K."},
                "text": {"text": "Best cold brew downtown!"},
                "rating": 5,
                "relativePublishTimeDescription": "a month ago",
            }
        ],
        "photos": [
            {
                "name": "places/ChIJtest123/photos/photoXYZ",
                "widthPx": 1200,
                "heightPx": 800,
                "authorAttributions": [{"displayName": "Photographer Dan", "uri": "https://maps.google.com/dan"}],
            }
        ],
    }

    settings = Settings(places_api_key="mock_key")

    def mock_handler(request: httpx.Request):
        assert request.headers["X-Goog-Api-Key"] == "mock_key"
        assert "places/ChIJtest123" in str(request.url)
        return httpx.Response(200, json=mock_payload)

    client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    details = fetch_place_details("ChIJtest123", settings=settings, client=client)

    assert details["name"] == "Austin Coffee Works"
    assert details["rating"] == 4.7
    assert details["website_confirmed_none"] is True
    assert len(details["reviews"]) == 1
    assert details["reviews"][0].author_name == "Sarah K."
    assert details["reviews"][0].text == "Best cold brew downtown!"
    assert len(details["photos"]) == 1
    assert details["photos"][0].author_name == "Photographer Dan"
    assert "coffee shop" in details["categories"]
    assert "cafe" in details["categories"]
    assert "point_of_interest" not in details["categories"]


def test_enrich_lead_service(test_db, ready_lead_id):
    mock_payload = {
        "id": "places/ChIJ12345678",
        "displayName": {"text": "Thistle Cafe"},
        "rating": 4.9,
        "userRatingCount": 42,
        "types": ["cafe"],
        "primaryType": "cafe",
        "websiteUri": None,
        "reviews": [
            {"authorAttribution": {"displayName": "John"}, "text": {"text": "Great spot!"}, "rating": 5},
            {"authorAttribution": {"displayName": "Mary"}, "text": {"text": "Friendly staff!"}, "rating": 5},
        ],
        "photos": [{"name": "places/p1"}],
    }

    settings = Settings(places_api_key="mock_key")

    def mock_handler(request: httpx.Request):
        return httpx.Response(200, json=mock_payload)

    client = httpx.Client(transport=httpx.MockTransport(mock_handler))

    enrichment = enrich_lead(test_db, ready_lead_id, settings=settings, client=client)
    assert enrichment.rating == 4.9
    assert enrichment.review_count == 42
    assert len(enrichment.top_reviews) == 2
    assert enrichment.website_confirmed_none is True
    assert enrichment.data_richness > 0.5
    assert enrichment.fetched_at is not None
    assert enrichment.expires_at is not None

    # Check persistence
    row = get_enrichment(test_db, ready_lead_id)
    assert row is not None
    assert row["rating"] == 4.9
    assert row["place_id"] == "places/ChIJ12345678"
    assert row["fetched_at"] is not None
    assert row["expires_at"] is not None


def test_enrich_refuses_non_ready_leads(test_db):
    # Status: new
    l_new = insert_lead(test_db, source="places", source_id="p_new", name="New Lead", status="new")
    with pytest.raises(ValueError, match="Only 'ready' leads can be enriched"):
        enrich_lead(test_db, l_new)

    # Status: verified
    l_ver = insert_lead(test_db, source="places", source_id="p_ver", name="Verified Lead", status="verified")
    with pytest.raises(ValueError, match="Only 'ready' leads can be enriched"):
        enrich_lead(test_db, l_ver)

    # Status: disqualified
    l_dis = insert_lead(test_db, source="places", source_id="p_dis", name="Disq Lead", status="disqualified")
    with pytest.raises(ValueError, match="Only 'ready' leads can be enriched"):
        enrich_lead(test_db, l_dis)

    # Status: dnc
    l_dnc = insert_lead(test_db, source="places", source_id="p_dnc", name="DNC Lead", status="dnc")
    with pytest.raises(ValueError, match="Only 'ready' leads can be enriched"):
        enrich_lead(test_db, l_dnc)


def test_purge_enrichment(test_db):
    l1 = insert_lead(test_db, source="places", source_id="p_exp", name="Expired Lead", status="ready")
    l2 = insert_lead(test_db, source="places", source_id="p_act", name="Active Lead", status="ready")

    # Expired 2 days ago
    past_iso = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    # Expires in 5 days
    future_iso = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()

    save_enrichment(
        test_db,
        lead_id=l1,
        place_id="places/ChIJExpired",
        rating=4.5,
        review_count=10,
        top_reviews_json=json.dumps([{"author_name": "Old", "text": "Old review"}]),
        photo_refs_json=json.dumps([{"name": "places/old/photo"}]),
        raw_json=json.dumps({"raw": "data"}),
        data_richness=0.75,
        expires_at=past_iso,
    )

    save_enrichment(
        test_db,
        lead_id=l2,
        place_id="places/ChIJActive",
        rating=4.9,
        review_count=25,
        top_reviews_json=json.dumps([{"author_name": "Current", "text": "Current review"}]),
        photo_refs_json=json.dumps([{"name": "places/current/photo"}]),
        raw_json=json.dumps({"raw": "current_data"}),
        data_richness=0.90,
        expires_at=future_iso,
    )

    purged_count = purge_expired_enrichment(test_db)
    assert purged_count == 1

    # Check expired lead: expiring fields purged, place_id and richness kept!
    row1 = get_enrichment(test_db, l1)
    assert row1["top_reviews_json"] is None
    assert row1["photo_refs_json"] is None
    assert row1["raw_json"] is None
    assert row1["place_id"] == "places/ChIJExpired"
    assert row1["data_richness"] == 0.75
    assert row1["rating"] == 4.5
    assert row1["review_count"] == 10

    # Check active lead: untouched!
    row2 = get_enrichment(test_db, l2)
    assert row2["top_reviews_json"] is not None
    assert row2["photo_refs_json"] is not None
    assert row2["raw_json"] is not None
    assert row2["place_id"] == "places/ChIJActive"
    assert row2["data_richness"] == 0.90

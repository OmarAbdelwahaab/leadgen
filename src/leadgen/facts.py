"""Assembly and export of verified facts for ready leads."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from leadgen.db import get_enrichment, get_lead
from leadgen.leads.verify import classify_website
from leadgen.phone import pretty_us

DAY_MAP = {
    "mo": "Mon", "tu": "Tue", "we": "Wed", "th": "Thu", "fr": "Fri", "sa": "Sat", "su": "Sun",
    "mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun",
    "monday": "Monday", "tuesday": "Tuesday", "wednesday": "Wednesday", "thursday": "Thursday",
    "friday": "Friday", "saturday": "Saturday", "sunday": "Sunday",
    "ph": "Public Holidays",
}


def _fmt_day_token(d: str) -> str:
    return DAY_MAP.get(d.strip().lower(), d.strip().capitalize())


def _format_day_expression(d_raw: str) -> str | None:
    d = d_raw.strip()
    if not d:
        return None
    if d.lower() == "ph":
        return "Public Holidays"
    if "-" in d or "–" in d:
        sep = "-" if "-" in d else "–"
        parts = [p.strip() for p in d.split(sep, 1)]
        if len(parts) == 2 and all(p.lower() in DAY_MAP for p in parts if p):
            return f"{_fmt_day_token(parts[0])}–{_fmt_day_token(parts[1])}"
    if "," in d:
        parts = [p.strip() for p in d.split(",")]
        if parts and all(p.lower() in DAY_MAP for p in parts if p):
            return ", ".join(_fmt_day_token(p) for p in parts)
    if d.lower() in DAY_MAP:
        return _fmt_day_token(d)
    return None


def _format_time_expression(t_raw: str) -> str | None:
    t = t_raw.strip()
    if not t:
        return None
    low = t.lower()
    if low in ("off", "closed"):
        return "Closed"
    if low in ("open", "24h", "24 hours", "open 24 hours"):
        return "Open 24 hours"
    if t == "24/7":
        return "Open 24/7"
    m = re.match(r"^(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})$", t)
    if m:
        h1, m1, h2, m2 = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
        if 0 <= h1 <= 24 and 0 <= h2 <= 24:
            def to_12h(h: int, mm: str) -> str:
                period = "AM" if (h < 12 or h == 24) else "PM"
                h12 = h % 12
                if h12 == 0:
                    h12 = 12
                return f"{h12}:{mm} {period}"
            return f"{to_12h(h1, m1)} – {to_12h(h2, m2)}"
    m_simple = re.match(r"^(\d{1,2})\s*[-–]\s*(\d{1,2})$", t)
    if m_simple:
        h1, h2 = int(m_simple.group(1)), int(m_simple.group(2))
        def to_12h_simple(h: int) -> str:
            period = "PM" if (h <= 7 or (12 <= h < 24)) else "AM"
            h12 = h % 12
            if h12 == 0:
                h12 = 12
            return f"{h12}:00 {period}"
        return f"{to_12h_simple(h1)} – {to_12h_simple(h2)}"
    if re.search(r"\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)", t, re.IGNORECASE):
        return re.sub(r"\s*[-–]\s*", " – ", t)
    return None


def _parse_single_hours_rule(rule: str) -> tuple[str, str] | None:
    rule = rule.strip()
    if not rule:
        return None
    if rule == "24/7":
        return ("Mon–Sun", "Open 24/7")
    if ":" in rule:
        idx = rule.find(":")
        prefix = rule[:idx].strip()
        if not re.search(r"\d", prefix):
            day_str = _format_day_expression(prefix)
            time_str = _format_time_expression(rule[idx + 1:])
            if day_str and time_str:
                return (day_str, time_str)
    m = re.match(r"^([A-Za-z,\-–]+)\s+(.*)$", rule)
    if m:
        day_str = _format_day_expression(m.group(1))
        time_str = _format_time_expression(m.group(2))
        if day_str and time_str:
            return (day_str, time_str)
    return None


class HoursItem(BaseModel):
    day: str
    text: str


def parse_hours(hours_raw: str | list[str] | None) -> list[HoursItem]:
    """Parse raw opening hours strings into structured HoursItem models."""
    if not hours_raw:
        return []
    if isinstance(hours_raw, str):
        try:
            items = json.loads(hours_raw)
            if not isinstance(items, list):
                items = [hours_raw]
        except json.JSONDecodeError:
            items = [hours_raw]
    elif isinstance(hours_raw, list):
        items = hours_raw
    else:
        return []

    rows: list[HoursItem] = []
    for item in items:
        if not isinstance(item, str):
            continue
        sub_rules = [r.strip() for r in item.split(";") if r.strip()]
        for sub in sub_rules:
            parsed = _parse_single_hours_rule(sub)
            if parsed:
                day, text = parsed
                rows.append(HoursItem(day=day[:20], text=text[:40]))
    return rows[:7]


def clean_address(addr: str | None, business_name: str | None = None) -> str | None:
    """Clean address string: remove country suffix and strip leading duplicate business name."""
    if not addr:
        return None
    s = addr.strip()
    if business_name:
        b_clean = business_name.strip()
        if s.lower().startswith(b_clean.lower() + ","):
            s = s[len(b_clean) + 1:].strip()
        elif s.lower().startswith(b_clean.lower()):
            s = s[len(b_clean):].lstrip(",").strip()

    s = re.sub(r",?\s*(?:United States of America|United States|USA|US)\.?\s*$", "", s, flags=re.IGNORECASE)
    s = s.rstrip(",").strip()
    return s or None


def slugify(name: str, suffix: str | int = "") -> str:
    """Generate URL-safe identifier base from business name."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:45] or "lead"
    return f"{base}-{suffix}" if suffix != "" else base


class PhoneFacts(BaseModel):
    display: str
    e164: str


class WebsiteStatus(BaseModel):
    status: str  # "none" | "social_only"
    links: list[str] = Field(default_factory=list)
    notes: str | None = None


class EnrichmentFacts(BaseModel):
    fetched_at: str | None = None
    expires_at: str | None = None
    review_snippets: list[dict[str, Any]] = Field(default_factory=list)
    photo_refs: list[dict[str, Any]] = Field(default_factory=list)
    attribution: str = "Google Places API"


class LeadFacts(BaseModel):
    """Strict, factual representation of a business lead with provenance. Zero design decisions."""
    lead_id: int
    name: str
    category: str | None = None
    phone: PhoneFacts
    address: str | None = None
    city: str | None = None
    state: str | None = None
    lat: float | None = None
    lng: float | None = None
    timezone: str | None = None
    hours: list[HoursItem] = Field(default_factory=list)
    rating: float | None = None
    rating_count: int | None = None
    categories: list[str] = Field(default_factory=list)
    place_id: str | None = None
    website_status: WebsiteStatus
    enrichment: EnrichmentFacts | None = None
    sources: dict[str, Any] = Field(default_factory=dict)
    generated_at: str


def build_facts_dict(conn: sqlite3.Connection, lead_id: int) -> dict[str, Any]:
    """Assemble verified business facts and provenance for a single lead.
    
    Contains NO theme, layout, copy direction, or styling decisions.
    """
    lead = get_lead(conn, lead_id)
    if lead is None:
        raise ValueError(f"Lead #{lead_id} not found in database")

    enrichment_row = get_enrichment(conn, lead_id)
    name = lead["name"]
    phone_e164 = lead["phone_e164"] or ""
    phone_display = pretty_us(phone_e164) if phone_e164 else ""

    # Parse hours
    parsed_hours = parse_hours(lead["hours_json"])

    # Categories
    categories: list[str] = []
    if enrichment_row and enrichment_row["categories_json"]:
        try:
            categories = json.loads(enrichment_row["categories_json"])
        except Exception:
            pass
    if not categories and lead["category"]:
        categories = [lead["category"]]

    # Place ID
    place_id = None
    if enrichment_row and enrichment_row["place_id"]:
        place_id = enrichment_row["place_id"]
    elif lead["source"] == "places" and lead["source_id"]:
        place_id = lead["source_id"]

    # Website status
    site_classification = classify_website(lead["website_uri"])
    status_str = "social_only" if site_classification == "social" else "none"
    links = [lead["website_uri"]] if lead["website_uri"] and site_classification == "social" else []
    website_status = WebsiteStatus(
        status=status_str,
        links=links,
        notes=lead["notes"],
    )

    # Enrichment (included ONLY if unexpired)
    enrichment_facts: EnrichmentFacts | None = None
    if enrichment_row:
        is_expired = False
        expires_at_str = enrichment_row["expires_at"]
        if expires_at_str:
            now_iso = datetime.now(timezone.utc).isoformat()
            if expires_at_str < now_iso:
                is_expired = True

        if not is_expired:
            top_reviews = []
            if enrichment_row["top_reviews_json"]:
                try:
                    top_reviews = json.loads(enrichment_row["top_reviews_json"])
                except Exception:
                    pass
            photo_refs = []
            if enrichment_row["photo_refs_json"]:
                try:
                    photo_refs = json.loads(enrichment_row["photo_refs_json"])
                except Exception:
                    pass

            if top_reviews or photo_refs or enrichment_row["fetched_at"]:
                enrichment_facts = EnrichmentFacts(
                    fetched_at=enrichment_row["fetched_at"],
                    expires_at=enrichment_row["expires_at"],
                    review_snippets=top_reviews,
                    photo_refs=photo_refs,
                    attribution="Google Places API",
                )

    # Rating and review count
    rating = enrichment_row["rating"] if (enrichment_row and enrichment_row["rating"] is not None) else lead["rating"]
    rating_count = (
        enrichment_row["review_count"]
        if (enrichment_row and enrichment_row["review_count"] is not None)
        else lead["rating_count"]
    )

    sources = {
        "lead_source": lead["source"],
        "name": lead["source"],
        "phone": lead["source"],
        "address": lead["source"],
        "hours": lead["source"],
        "website_verification": "search_api" if lead["website_checked"] else "source_data",
        "enrichment": "google_places" if enrichment_facts else None,
    }

    facts = LeadFacts(
        lead_id=lead_id,
        name=name,
        category=lead["category"],
        phone=PhoneFacts(display=phone_display, e164=phone_e164),
        address=clean_address(lead["address"], name),
        city=lead["city"],
        state=lead["state"],
        lat=lead["lat"],
        lng=lead["lng"],
        timezone=lead["timezone"],
        hours=parsed_hours,
        rating=rating,
        rating_count=rating_count,
        categories=categories,
        place_id=place_id,
        website_status=website_status,
        enrichment=enrichment_facts,
        sources=sources,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    return facts.model_dump()


def export_facts_for_lead(
    conn: sqlite3.Connection,
    lead_id: int,
    base_dir: Path | str = "packets",
) -> Path:
    """Export facts for a single 'ready' lead into packets/<slug>-<id>/facts.json."""
    lead = get_lead(conn, lead_id)
    if lead is None:
        raise ValueError(f"Lead #{lead_id} not found in database")
    if lead["status"] != "ready":
        raise ValueError(f"Lead #{lead_id} is not 'ready' (current status: '{lead['status']}'). Only ready leads can be exported.")

    facts = build_facts_dict(conn, lead_id)
    slug = slugify(lead["name"])
    packet_dir = Path(base_dir) / f"{slug}-{lead_id}"
    packet_dir.mkdir(parents=True, exist_ok=True)

    facts_path = packet_dir / "facts.json"
    facts_path.write_text(json.dumps(facts, indent=2), encoding="utf-8")
    return facts_path


def export_all_ready_facts(
    conn: sqlite3.Connection,
    base_dir: Path | str = "packets",
) -> list[Path]:
    """Export facts for all leads with status 'ready'."""
    exported_paths: list[Path] = []
    rows = conn.execute("SELECT id FROM leads WHERE status = 'ready' ORDER BY id ASC").fetchall()
    for row in rows:
        path = export_facts_for_lead(conn, row["id"], base_dir=base_dir)
        exported_paths.append(path)
    return exported_paths

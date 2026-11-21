# AGENTS.md: Leadgen

Project: a standalone lead-generation and facts-export system that finds US local businesses with no website, verifies eligibility, screens against Do Not Call (DNC) records, optionally enriches records with Places API details, and produces verified fact packets (`packets/<slug>-<id>/facts.json`) for downstream design agents.

## Core Mandates
1. **Never change the leads table columns without updating docs/integration.md.** The `leads` table schema is a strict cross-system integration contract.
2. **Zero design logic.** This repository must contain NO website templates, HTML renderers, Jinja2 templates, CSS styling, theme selections, copy direction, or visual decisions.
3. **Status flow:**
   - `new` -> Discovered candidate from finder (OSM, Places, Geoapify) or CSV import.
   - `verified` -> Verified to have valid E.164 phone, valid timezone from coordinates, and no real website.
   - `ready` -> Scrubbed against internal DNC list. Only `ready` leads may be enriched or exported.
   - `disqualified` -> Has an active website, invalid phone format, or missing geographic coordinates.
   - `dnc` -> Phone number exists in `dnc` table.
4. **Enrichment is strictly optional and post-qualification:**
   - Only `ready` leads may be enriched (`leadgen enrich <id>`).
   - Enrichment content (reviews, photo references, raw JSON) expires according to `ENRICHMENT_TTL_DAYS`.
   - `leadgen purge-enrichment` purges expired fields while keeping place ID and richness scores.
5. **No Google Maps scraping:** Official Places API, OpenStreetMap Overpass, Geoapify, or user-provided CSV only.

## Stack & Conventions
- Python 3.11+, package in `src/leadgen/`, tests in `tests/` (`pytest -q`).
- SQLite via stdlib `sqlite3` (`src/leadgen/db.py`). No ORM.
- Pydantic v2 models for structured schemas.
- CLI defined via `argparse` in `src/leadgen/cli.py`.

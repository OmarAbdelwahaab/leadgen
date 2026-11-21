# Leadgen

Standalone local business lead finder, verifier, optional enrichment engine, and facts exporter.

## Purpose

Leadgen discovers US local businesses with no website across official Places API, OpenStreetMap, Geoapify, or CSV imports. It normalizes phone numbers, verifies web absence (filtering aggregators and social profiles), screens internal DNC, optionally fetches enrichment details, and exports clean, objective fact packets (`packets/<slug>-<id>/facts.json`) for downstream agents.

Leadgen contains **no site generation, templates, copy direction, or styling decisions**.

## Installation

```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -e ".[dev]"
```

## Quick Start

```bash
# 1. Initialize database
leadgen init-db

# 2. Find leads from OSM, Geoapify, or Google Places
leadgen find-leads "plumber" "Austin, TX" --source osm

# 3. Verify phone, timezone, and lack of website (moves to verified -> ready)
leadgen verify

# 4. Check status stats
leadgen stats

# 5. (Optional) Enrich a ready lead with Google Places reviews and photos
leadgen enrich 1

# 6. Export verified facts for downstream site design
leadgen export-facts --all-ready
```

## Lead Lifecycle

1. `new`: Discovered candidate from finder or CSV import.
2. `verified`: Passed phone normalization, coordinate timezone resolution, and website absence check.
3. `ready`: Screened against internal DNC list and confirmed callable/actionable.
4. `disqualified`: Has a real website, invalid phone, or missing coordinates.
5. `dnc`: Number matched on internal Do Not Call list.

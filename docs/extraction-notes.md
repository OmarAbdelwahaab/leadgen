# Leadgen Extraction Notes & Dependency Map

This document records the dependency trace and architectural extraction plan from `ai-web-agency` (branch `feat/design-ab-test`) into the standalone `leadgen` project.

---

## 1. Trace of Leads Modules (`src/agency/leads/*.py`)

### `csv_import.py`
- **Imports:** `csv`, `hashlib`, `json`, `re`, `sqlite3`, `pathlib.Path`
- **Internal Dependencies:**
  - `agency.db`: `insert_lead`, `phone_in_leads`
  - `agency.phone`: `to_e164`
- **DB Tables Reached:** `leads` (inserts new leads, deduplicates via phone across formats).
- **Settings Reached:** None directly (parameters passed in or defaulted).
- **Extraction Destination:** `src/leadgen/leads/csv_import.py` (imports updated to `leadgen.*`).

### `geoapify.py`
- **Imports:** `json`, `logging`, `sqlite3`, `typing.Any`, `httpx`
- **Internal Dependencies:**
  - `agency.config`: `Settings`, `get_settings` (reads `s.geoapify_api_key`)
  - `agency.db`: `insert_lead`, `phone_in_leads`
  - `agency.phone`: `to_e164`
- **DB Tables Reached:** `leads`.
- **Settings Reached:** `geoapify_api_key`.
- **Extraction Destination:** `src/leadgen/leads/geoapify.py`.

### `osm.py`
- **Imports:** `json`, `logging`, `sqlite3`, `httpx`
- **Internal Dependencies:**
  - `agency.config`: `Settings`, `get_settings` (reads `s.overpass_url`)
  - `agency.db`: `insert_lead`, `phone_in_leads`
  - `agency.phone`: `to_e164`
- **DB Tables Reached:** `leads`.
- **Settings Reached:** `overpass_url`.
- **Extraction Destination:** `src/leadgen/leads/osm.py`.

### `places.py`
- **Imports:** `json`, `logging`, `sqlite3`, `httpx`
- **Internal Dependencies:**
  - `agency.config`: `Settings`, `get_settings` (reads `s.places_api_key`)
  - `agency.db`: `insert_lead`, `phone_in_leads`
  - `agency.phone`: `to_e164`
- **DB Tables Reached:** `leads`.
- **Settings Reached:** `places_api_key`.
- **Extraction Destination:** `src/leadgen/leads/places.py`.

### `verify.py`
- **Imports:** `logging`, `sqlite3`, `functools.lru_cache`, `urllib.parse.urlparse`, `httpx`, `timezonefinder.TimezoneFinder`
- **Internal Dependencies:**
  - `agency.config`: `Settings`, `get_settings` (reads `s.search_api_key`, `s.search_engine_id`)
  - `agency.phone`: `to_e164`
  - `agency.compliance.gates`: `is_dnc` (used in `scrub_all`)
- **DB Tables Reached:** `leads` (updates status: `verified`, `disqualified`, `ready`, `dnc`), `dnc`.
- **Settings Reached:** `search_api_key`, `search_engine_id`.
- **Extraction Destination:** `src/leadgen/leads/verify.py`.

---

## 2. Trace of Enrichment Modules (`src/agency/enrichment/*.py`)

### `models.py`
- **Dependencies:** `pydantic.BaseModel`, `pydantic.Field`, `typing.Any`.
- **Models:**
  - `ReviewSnippet`: Customer review with author attribution. Moves to `leadgen`.
  - `PhotoReference`: Google Places photo metadata with author attribution. Moves to `leadgen`.
  - `LeadEnrichment`: Aggregated enrichment data for a lead. Moves to `leadgen`.
  - `ImageInfo`: Concrete image asset model for static site rendering. **FLAGGED: Stays behind.**
- **Extraction Destination:** `src/leadgen/enrichment/models.py`.

### `places_details.py`
- **Imports:** `logging`, `typing.Any`, `httpx`
- **Internal Dependencies:**
  - `agency.config`: `Settings`, `get_settings` (reads `s.places_api_key`)
  - `agency.enrichment.models`: `PhotoReference`, `ReviewSnippet`
  - `agency.retry`: `retry`
- **Settings Reached:** `places_api_key`.
- **Extraction Destination:** `src/leadgen/enrichment/places_details.py`.

### `score.py`
- **Imports:** `json`, `sqlite3`, `typing.Any`
- **Internal Dependencies in Source Repo:**
  - `agency.config`: `get_settings` (reads `richness_threshold` in `is_rich_lead`) -> **FLAGGED: Template-era gating. Remove!**
  - `agency.enrichment.models`: `LeadEnrichment`
  - `agency.sitegen.schema`: `parse_hours` -> **FLAGGED: Sitegen dependency. Move hours parsing into leadgen facts module!**
- **Changes for Leadgen:**
  - Remove `is_rich_lead()` and `richness_threshold`.
  - Keep `compute_data_richness()` as an informational 0.0 - 1.0 completeness score.
  - Drop dependency on `local_image_count` / `LocalAssetSource` (photos scored purely on `photo_refs`).
  - Import `parse_hours` from `leadgen.facts`.
- **Extraction Destination:** `src/leadgen/enrichment/score.py`.

### `service.py`
- **Imports:** `json`, `logging`, `sqlite3`, `httpx`
- **Internal Dependencies in Source Repo:**
  - `agency.config`: `Settings`, `get_settings`
  - `agency.db`: `add_owner_note`, `get_enrichment`, `get_lead`, `save_enrichment`
  - `agency.enrichment.images`: `LocalAssetSource` -> **FLAGGED: Stays behind.**
  - `agency.enrichment.models`: `LeadEnrichment`, `PhotoReference`, `ReviewSnippet`
  - `agency.enrichment.places_details`: `fetch_place_details`
  - `agency.enrichment.score`: `compute_data_richness`
  - `agency.leads`: `places`
- **Changes for Leadgen:**
  - Remove `LocalAssetSource` and local asset reading.
  - Remove `record_owner_note()` (call-time notes logic stays behind).
  - Enforce enrichment rule: refuse any lead whose status is not `ready`.
  - Store `place_id` on enrichment.
  - Add `fetched_at` and `expires_at` based on `ENRICHMENT_TTL_DAYS`.
- **Extraction Destination:** `src/leadgen/enrichment/service.py`.

### `images.py`
- **FLAGGED: STAYS BEHIND.** Contains `ImageSourceAdapter`, `LocalAssetSource`, `StockImageSource`, and `CompositeImageSource` for template rendering and local disk asset loading.

---

## 3. Facts vs. Design in `src/agency/sitegen/brief.py`

`src/agency/sitegen/brief.py` previously served as a dual-purpose generator: compiling verified business facts AND prescribing visual design directives for site builders.

### A. Facts-Assembly Logic (MOVES to `leadgen.facts`)
- Lead identity & location: `lead_id`, `name`, `slug`, `category`, `address`, `city`, `state`, `lat`, `lng`, `timezone`.
- Phone handling: E.164 normalization and formatted US national display string via `phone.pretty_us`.
- Address cleaning: `clean_address` stripping redundant business prefixes and USA country suffixes.
- Operating hours: `parse_hours` structured parsing of weekday times from JSON/OSM strings into day/text tuples.
- Ratings & reviews: `rating`, `rating_count`, review snippets with author attributions.
- Photo references: Google Places photo IDs with mandatory photographer attribution.
- Categories taxonomy: Extracted from Places details or lead classification.
- Place ID: Preserved from Places search/details.
- Website status: Whether site is absent (`none`) or social-only (`social_only`), plus any discovered links.
- Provenance/Sources: Source tagging indicating which finder/enricher populated the record.
- Serializing structured output to `packets/<slug>-<id>/facts.json`.

### B. Design Logic (FLAGGED: STAYS BEHIND IN OLD REPO)
- `theme_for_category()`: Categorizing businesses into pre-baked template themes (`food`, `health`, `trades`, `retail`).
- `design_constraints`: List of hardcoded styling rules ("Single-page static HTML with inline CSS...", "Mobile-first on 375px phone screen...", "Primary click-to-call button prominently linked...").
- `agency_credit`: Branding watermark text ("Website by Your Agency").
- `render_brief_markdown()`: Markdown document formatting with "Design Intent", layout directives, and copy instructions.
- Design workspace provisioning: Writing to `sites-workspace/<slug>/` and copying image files into `assets/`.

---

## 4. Other Modules and Components

### Database Helpers (`agency.db` -> `leadgen.db`)
- **Functions moving:** `connect`, `init_db`, `insert_lead`, `get_lead`, `phone_in_leads`, `save_enrichment`, `get_enrichment`.
- **Tables moving:**
  - `leads`: Kept **column-for-column identical**. `LEAD_STATUSES` tuple kept intact. Leadgen writes: `new`, `verified`, `ready`, `disqualified`, `dnc`.
  - `dnc`: Kept identical (`phone_e164`, `reason`, `added_at`).
  - `lead_enrichment`: Adds `place_id`, `fetched_at`, and `expires_at`.
- **Tables staying behind:** `calls`, `gate_log`, `clients`, `legal_reviews`, `design_scores`.
- **Functions staying behind:** `record_legal_review`, `has_legal_review`, `add_owner_note`, `record_design_score`, `get_design_scores`.

### Compliance (`agency.compliance.gates` -> `leadgen.compliance.gates`)
- **Functions moving:** `is_dnc`, `add_dnc`.
- **Staying behind:** `can_dial`, `within_calling_window`, `local_now`, calling windows, legal review signoffs, attempt caps.

### Reporting (`agency.reporting` -> `leadgen.reporting`)
- **Functions moving:** `export_table_to_csv`, and a lightweight `stats` function for lead counts by status.
- **Staying behind:** `get_dashboard_stats`, `render_dashboard`, `export_all_to_csv` for client/call tables.

### Utility Modules Moving
- `phone.py`: `to_e164`, `pretty_us`.
- `logging_config.py`: `setup_logging`, `JSONFormatter`.
- `retry.py`: `retry` decorator for robust external API calls.

### Configuration (`leadgen.config.Settings`)
- Trimmed to ONLY the settings required for leadgen:
  - `db_path`: Default `data/leads.db`
  - `places_api_key`
  - `geoapify_api_key`
  - `overpass_url`
  - `search_api_key`
  - `search_engine_id`
  - `leads_csv_path`: Default `leads.csv`
  - `log_format`: Default `text`
  - `enrichment_ttl_days`: Default `7`

### Flagged Subsystems Completely Excluded
- Voice Caller: `agency.voice.*`, LiveKit, SIP trunk, STT, TTS, Groq audio.
- Site Generator: `agency.sitegen.*`, Jinja2 templates, AI fill, QA detectors, Playwright screenshotting, HTML rendering.
- Post-Sale / Notify: `agency.notify.*`, Telegram bot, `agency.pipeline.*`.
- Payments: `agency.payments.*`, Stripe integrations.

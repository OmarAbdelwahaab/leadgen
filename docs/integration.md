# Leadgen Integration Contract

This document defines the interface, data schema, and consumption contract between `leadgen` and downstream consumers (such as design agents, site generators, or CRM pipelines).

---

## 1. The Rule

> **Never change the `leads` table columns without updating `docs/integration.md`.**
> 
> The database schema of the `leads` table and exported `leads.csv` represents a shared integration contract across projects.

---

## 2. Leads Table Schema & `leads.csv`

The `leads` table is identical column-for-column across versions. Leadgen writes only the following statuses: `new`, `verified`, `ready`, `disqualified`, and `dnc`.

### Column Definitions

| Column | Type | Default | Description |
|---|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Auto | Internal unique lead identifier |
| `source` | `TEXT NOT NULL` | None | Origin finder (`osm`, `places`, `geoapify`, `csv`, `manual`) |
| `source_id` | `TEXT` | `NULL` | Source-specific identifier (e.g. Places ID, OSM node ID) |
| `name` | `TEXT NOT NULL` | None | Business name |
| `category` | `TEXT` | `NULL` | Primary trade or category label (e.g. `plumber`, `cafe`) |
| `phone_e164` | `TEXT` | `NULL` | Standardized E.164 phone string (e.g. `+15125550100`) |
| `address` | `TEXT` | `NULL` | Street address |
| `city` | `TEXT` | `NULL` | Locality or town |
| `state` | `TEXT` | `NULL` | Two-letter state code or region |
| `lat` | `REAL` | `NULL` | Latitude coordinate |
| `lng` | `REAL` | `NULL` | Longitude coordinate |
| `timezone` | `TEXT` | `NULL` | IANA timezone string derived from coordinates (e.g. `America/Chicago`) |
| `website_uri` | `TEXT` | `NULL` | Discovered website link (if any, e.g. social profile) |
| `website_checked`| `INTEGER NOT NULL` | `0` | `1` if search API was queried to verify lack of web presence, `0` otherwise |
| `rating` | `REAL` | `NULL` | Star rating (1.0 to 5.0) |
| `rating_count` | `INTEGER` | `NULL` | Total user review count |
| `business_status`| `TEXT` | `NULL` | Operational status (`OPERATIONAL`, etc.) |
| `hours_json` | `TEXT` | `NULL` | JSON array of raw opening hours strings |
| `status` | `TEXT NOT NULL` | `'new'` | Current lead lifecycle status |
| `attempts` | `INTEGER NOT NULL` | `0` | Outbound contact attempts (managed downstream) |
| `callback_at` | `TEXT` | `NULL` | Scheduled callback timestamp |
| `notes` | `TEXT` | `NULL` | Verification notes or operator notes |
| `raw_json` | `TEXT` | `NULL` | Raw JSON payload from the original data source |
| `created_at` | `TEXT NOT NULL` | `datetime('now')` | Lead discovery timestamp |

Constraints: `UNIQUE(source, source_id)`.

---

## 3. Lead Lifecycle Statuses

- `new`: Candidate newly ingested from finder or CSV import. Unverified.
- `verified`: Qualified by `leadgen verify`: has a valid E.164 phone, valid geographic timezone, and confirmed lack of a real website.
- `ready`: Qualified and scrubbed against the internal DNC list. Only `ready` leads can be enriched or exported.
- `disqualified`: Rejected due to existing real website, invalid phone format, or missing coordinates.
- `dnc`: Number matched on internal Do Not Call list.
- *(Reserved downstream statuses: `calling`, `yes`, `no`, `callback`, `voicemail`)*.

---

## 4. `facts.json` Schema & Downstream Consumption

Downstream projects (e.g., custom site design agents) consume lead packages by reading:
```
packets/<slug>-<id>/facts.json
```

`facts.json` contains **pure factual data and provenance only**. It contains zero theme, layout, or copy prescriptions.

### Top-Level Keys

- `lead_id` (`int`): Unique lead ID.
- `name` (`str`): Legal or trade business name.
- `category` (`str | None`): Category label.
- `phone` (`object`):
  - `display`: Formatted US national format (e.g., `"(512) 555-0100"`).
  - `e164`: E.164 normalized format (e.g., `"+15125550100"`).
- `address` (`str | None`): Cleaned street address (stripped of country suffix).
- `city` (`str | None`): City name.
- `state` (`str | None`): Two-letter US state code.
- `lat` (`float | None`): Latitude.
- `lng` (`float | None`): Longitude.
- `timezone` (`str | None`): IANA timezone identifier.
- `hours` (`list[object]`): Parsed opening hours rows, each with `day` and `text`.
- `rating` (`float | None`): Star rating.
- `rating_count` (`int | None`): Number of reviews.
- `categories` (`list[str]`): Refined business taxonomy types.
- `place_id` (`str | None`): Google Places ID if known.
- `website_status` (`object`):
  - `status`: `"none"` or `"social_only"`.
  - `links`: Array of existing social URLs (e.g. Facebook page).
  - `notes`: Verification audit notes.
- `enrichment` (`object | None`): Included **only if unexpired**:
  - `fetched_at`: ISO UTC timestamp when details were retrieved.
  - `expires_at`: ISO UTC timestamp when cached details expire.
  - `review_snippets`: List of authentic reviews (`author_name`, `text`, `rating`, `relative_publish_time`).
  - `photo_refs`: List of photo reference tokens with mandatory photographer attribution.
  - `attribution`: Source attribution string (`"Google Places API"`).
- `sources` (`object`): Field-level provenance mapping showing which finder or service populated each data field.
- `generated_at` (`str`): ISO timestamp when the facts file was created.

### Example `facts.json`

```json
{
  "lead_id": 42,
  "name": "Austin Master Plumbing",
  "category": "plumber",
  "phone": {
    "display": "(512) 555-0144",
    "e164": "+15125550144"
  },
  "address": "404 Colorado St",
  "city": "Austin",
  "state": "TX",
  "lat": 30.2672,
  "lng": -97.7431,
  "timezone": "America/Chicago",
  "hours": [
    {
      "day": "Mon–Fri",
      "text": "8:00 AM – 5:00 PM"
    },
    {
      "day": "Sat",
      "text": "9:00 AM – 1:00 PM"
    }
  ],
  "rating": 4.8,
  "rating_count": 34,
  "categories": [
    "plumber",
    "emergency plumbing"
  ],
  "place_id": "places/ChIJMasterPlumb123",
  "website_status": {
    "status": "social_only",
    "links": [
      "https://facebook.com/austinmasterplumbing"
    ],
    "notes": "website=social"
  },
  "enrichment": {
    "fetched_at": "2026-11-20T10:00:00Z",
    "expires_at": "2026-11-27T10:00:00Z",
    "review_snippets": [
      {
        "author_name": "David R.",
        "text": "Fixed our burst pipe within an hour of calling. Outstanding work.",
        "rating": 5.0,
        "relative_publish_time": "2 weeks ago"
      }
    ],
    "photo_refs": [
      {
        "name": "places/ChIJMasterPlumb123/photos/photo_abc",
        "author_name": "Austin Master Plumbing",
        "author_uri": null,
        "width_px": 1200,
        "height_px": 800
      }
    ],
    "attribution": "Google Places API"
  },
  "sources": {
    "lead_source": "places",
    "name": "places",
    "phone": "places",
    "address": "places",
    "hours": "places",
    "website_verification": "search_api",
    "enrichment": "google_places"
  },
  "generated_at": "2026-11-21T23:50:00Z"
}
```

---

## 5. Google Places Terms, Caching & Compliance

### Places API Terms of Service Notice
Google Maps Platform Terms of Service govern all data retrieved via Google Places API:
1. **Place IDs may be stored indefinitely**: `place_id` (or `id`) is permitted for long-term indexing.
2. **Places Content Caching Restrictions**: Other Place Details content—specifically review text, user ratings, photo references, and raw API responses—must NOT be stored permanently. Temporary caching is permitted solely for performance optimization up to 30 days.
3. **TTL Enforcement in Leadgen**:
   - `leadgen` sets an expiration timestamp on all enrichment records controlled by `ENRICHMENT_TTL_DAYS` (default 7 days).
   - If an enrichment record has expired (`expires_at < now`), `leadgen export-facts` **omits the enrichment block**.
   - Running `leadgen purge-enrichment` permanently deletes `top_reviews_json`, `photo_refs_json`, and `raw_json` from expired records while preserving `place_id` and the calculated `data_richness` score.
4. **Mandatory Attribution**:
   - Review snippets must never be edited, altered, or presented without the original `author_name`.
   - Photos must display the photographer attribution (`author_name` / `author_uri`).
   - Downstream site builders must adhere to Google's attribution display requirements if presenting Google Places content.

### Compliance Risks for Legal Review
- **Content retention beyond TTL**: Ensure automated crons run `leadgen purge-enrichment` periodically.
- **Fair presentation**: Downstream consumers must never synthesize fake reviews or misattribute Google Places reviews as editorial endorsements.

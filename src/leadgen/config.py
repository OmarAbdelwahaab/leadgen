from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _time(name: str, default: str) -> time:
    h, m = os.environ.get(name, default).split(":")
    return time(int(h), int(m))


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.environ.get("DB_PATH", "data/leads.db")))
    places_api_key: str = field(default_factory=lambda: os.environ.get("GOOGLE_PLACES_API_KEY", ""))
    geoapify_api_key: str = field(default_factory=lambda: os.environ.get("GEOAPIFY_API_KEY", ""))
    overpass_url: str = field(default_factory=lambda: os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter"))
    search_api_key: str = field(default_factory=lambda: os.environ.get("SEARCH_API_KEY", ""))
    search_engine_id: str = field(default_factory=lambda: os.environ.get("SEARCH_ENGINE_ID", ""))
    leads_csv_path: Path = field(default_factory=lambda: Path(os.environ.get("LEADS_CSV_PATH", "leads.csv")))
    log_format: str = field(default_factory=lambda: os.environ.get("LOG_FORMAT", "text"))
    enrichment_ttl_days: int = field(default_factory=lambda: int(os.environ.get("ENRICHMENT_TTL_DAYS", "7")))


def get_settings() -> Settings:
    return Settings()

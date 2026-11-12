from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import API_URL, DEFAULT_FETCH_LIMIT, REQUEST_TIMEOUT_SECONDS
from database import upsert_tickets

# Only fields documented by the official NYC Open Data dataset are requested.
SOURCE_FIELDS = [
    "unique_key", "created_date", "closed_date", "agency", "agency_name",
    "complaint_type", "descriptor", "incident_zip", "borough", "status",
    "due_date", "resolution_description", "resolution_action_updated_date"
]
REQUIRED_SOURCE_FIELDS = {"unique_key", "created_date", "status"}


class SourceDataError(RuntimeError):
    """Raised when the public source cannot be fetched or validated."""


def get_source_metadata() -> dict[str, str]:
    """Scrape basic title/description from the official dataset landing page."""
    from config import SOURCE_URL

    response = requests.get(
        SOURCE_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": "ServiceOpsDemo/1.0 (educational project)"}
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": "description"})
    description = description_tag.get("content", "").strip() if description_tag else ""
    return {"title": title, "description": description}


def fetch_recent_tickets(limit: int = DEFAULT_FETCH_LIMIT) -> pd.DataFrame:
    """Fetch the newest source records through the official Socrata JSON API."""
    if not 1 <= int(limit) <= 10000:
        raise ValueError("limit must be between 1 and 10000")

    params = {
        "$select": ",".join(SOURCE_FIELDS),
        "$where": "created_date IS NOT NULL",
        "$order": "created_date DESC",
        "$limit": int(limit),
    }
    headers = {
        "Accept": "application/json",
        "User-Agent": "ServiceOpsDemo/1.0 (educational project; contact: student project)"
    }

    try:
        response = requests.get(
            API_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        payload: Any = response.json()
    except requests.RequestException as exc:
        raise SourceDataError(f"Network/API request failed: {exc}") from exc
    except ValueError as exc:
        raise SourceDataError("The source returned a non-JSON response.") from exc

    if not isinstance(payload, list):
        raise SourceDataError("Unexpected source format: expected a JSON array.")
    if not payload:
        raise SourceDataError("The source returned zero records. No data was replaced.")

    frame = pd.DataFrame(payload)
    missing = REQUIRED_SOURCE_FIELDS - set(frame.columns)
    if missing:
        raise SourceDataError(f"Source schema is missing required fields: {sorted(missing)}")

    # Optional columns can be absent if the publisher changes the schema.
    for field in SOURCE_FIELDS:
        if field not in frame.columns:
            frame[field] = pd.NA

    frame = frame[SOURCE_FIELDS].copy()
    frame["unique_key"] = frame["unique_key"].astype("string").str.strip()
    frame = frame[frame["unique_key"].notna() & (frame["unique_key"] != "")]
    frame = frame.drop_duplicates(subset=["unique_key"], keep="first")

    if frame.empty:
        raise SourceDataError("No valid unique request IDs were returned.")

    # Parse timestamps without silently fabricating replacements.
    for col in ["created_date", "closed_date", "due_date", "resolution_action_updated_date"]:
        frame[col] = pd.to_datetime(frame[col], errors="coerce", utc=True)
        frame[col] = frame[col].map(
            lambda x: x.isoformat() if pd.notna(x) else None
        )

    text_columns = [
        "agency", "agency_name", "complaint_type", "descriptor", "incident_zip",
        "borough", "status", "resolution_description"
    ]
    for col in text_columns:
        frame[col] = frame[col].map(
            lambda value: None if pd.isna(value) or str(value).strip() == "" else str(value).strip()
        )

    frame["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return frame


def ingest_recent_tickets(limit: int = DEFAULT_FETCH_LIMIT) -> dict[str, int]:
    """Fetch, validate and upsert source records. Existing records are not wholesale deleted."""
    frame = fetch_recent_tickets(limit=limit)
    changed = upsert_tickets(frame)
    return {"fetched": len(frame), "inserted_or_updated": changed}
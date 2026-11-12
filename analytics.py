from __future__ import annotations

import pandas as pd


def prepare_ticket_frame(raw: pd.DataFrame, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """Create analysis-only fields while preserving source columns."""
    df = raw.copy()
    rename = {
        "problem": "problem",
        "problem_detail": "problem_detail",
    }
    df = df.rename(columns=rename)

    for col in ["created_date", "closed_date", "due_date", "resolution_action_updated_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True).dt.tz_convert(None)

    current = now if now is not None else pd.Timestamp.now(tz="UTC").tz_localize(None)
    if current.tzinfo is not None:
        current = current.tz_convert(None)

    df["age_days"] = (current - df["created_date"]).dt.total_seconds() / 86400
    df.loc[df["closed_date"].notna(), "age_days"] = (
        df.loc[df["closed_date"].notna(), "closed_date"]
        - df.loc[df["closed_date"].notna(), "created_date"]
    ).dt.total_seconds() / 86400

    df["resolution_hours"] = (
        (df["closed_date"] - df["created_date"]).dt.total_seconds() / 3600
    )
    df.loc[df["resolution_hours"] < 0, "resolution_hours"] = pd.NA
    df.loc[df["age_days"] < 0, "age_days"] = pd.NA

    return df


def calculate_kpis(df: pd.DataFrame) -> dict[str, float | int]:
    total = int(len(df))
    open_count = int(df["closed_date"].isna().sum()) if total else 0
    closed_count = int(df["closed_date"].notna().sum()) if total else 0
    avg_hours = df.loc[df["closed_date"].notna(), "resolution_hours"].dropna().mean() if total else pd.NA
    return {
        "total": total,
        "open": open_count,
        "closed": closed_count,
        "avg_resolution_hours": float(avg_hours) if pd.notna(avg_hours) else float("nan"),
    }

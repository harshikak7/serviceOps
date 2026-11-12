import pandas as pd
from analytics import prepare_ticket_frame, calculate_kpis


def test_resolution_and_open_age_are_calculated_from_timestamps():
    source = pd.DataFrame([
        {"ticket_id": "A", "created_date": "2026-01-01T00:00:00Z",
         "closed_date": "2026-01-02T12:00:00Z", "due_date": None},
        {"ticket_id": "B", "created_date": "2026-01-02T00:00:00Z",
         "closed_date": None, "due_date": None},
    ])
    now = pd.Timestamp("2026-01-04T00:00:00")
    result = prepare_ticket_frame(source, now=now)
    assert result.loc[0, "resolution_hours"] == 36
    assert result.loc[1, "age_days"] == 2


def test_kpi_counts_use_closed_date_not_assumed_status_labels():
    frame = pd.DataFrame({
        "closed_date": [None, "2026-01-02", None],
        "resolution_hours": [None, 24, None]
    })
    result = calculate_kpis(frame)
    assert result["total"] == 3
    assert result["open"] == 2
    assert result["closed"] == 1
    assert result["avg_resolution_hours"] == 24

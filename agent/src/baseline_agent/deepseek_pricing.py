from __future__ import annotations

from datetime import UTC, datetime


def time_of_use_tier_at(observed_at: datetime) -> str:
    if observed_at.tzinfo is None:
        raise ValueError("pricing observation must be timezone-aware")
    observed_utc = observed_at.astimezone(UTC)
    is_peak = observed_utc.weekday() < 5 and (
        1 <= observed_utc.hour < 4 or 6 <= observed_utc.hour < 10
    )
    return "peak" if is_peak else "off-peak"

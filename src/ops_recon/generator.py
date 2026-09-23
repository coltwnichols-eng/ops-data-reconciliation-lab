"""Deterministic, wholly invented service-operations fixtures."""

import csv
from pathlib import Path


AS_OF = "2026-09-23T12:00:00Z"


def _write(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate_fixture(directory: str | Path, *, clean: bool = False) -> dict[str, Path]:
    """Write passing or intentionally failing sample CSVs into ``directory``."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    events = [
        ("EV-001", "TK-101", "North", "2026-09-23T08:00:00Z", "created", "0"),
        ("EV-002", "TK-101", "North", "2026-09-23T09:00:00Z", "worked", "30"),
        ("EV-003", "TK-102", "South", "2026-09-23T09:30:00Z", "worked", "20"),
        ("EV-004", "TK-103", "North", "2026-09-23T10:00:00Z", "worked", "25"),
        ("EV-006", "TK-104", "North", "2026-09-23T11:15:00Z", "worked", "15"),
        ("EV-007", "TK-105", "South", "2026-09-23T11:00:00Z", "worked", "40"),
        ("EV-008", "TK-106", "South", "2026-09-23T11:30:00Z", "worked", "15"),
        ("EV-009", "TK-107", "West", "2026-09-23T11:10:00Z", "worked", "12"),
        ("EV-010", "TK-108", "Central", "2026-09-23T07:30:00Z", "worked", "5"),
    ]
    if not clean:
        # A duplicate delivery and a row with no ticket identifier must not
        # inflate the operational totals.
        events.insert(4, events[3])
        events.insert(5, ("EV-005", "", "North", "2026-09-23T10:20:00Z", "worked", "10"))

    summary = [
        ("2026-09-23", "North", "4" if clean else "3", "70" if clean else "55", "2026-09-23T11:40:00Z" if clean else "2026-09-23T11:00:00Z"),
        ("2026-09-23", "South", "3", "75", "2026-09-23T11:45:00Z"),
        ("2026-09-23", "Central", "1", "5", "2026-09-23T11:40:00Z"),
    ]
    if clean:
        summary.append(("2026-09-23", "West", "1", "12", "2026-09-23T11:40:00Z"))
    else:
        summary.append(("2026-09-23", "East", "1", "10", "2026-09-23T11:45:00Z"))

    heartbeats = [
        ("North", "2026-09-23T11:50:00Z"),
        ("South", "2026-09-23T11:50:00Z"),
        ("West", "2026-09-23T11:52:00Z"),
        ("Central", "2026-09-23T11:40:00Z" if clean else "2026-09-23T08:00:00Z"),
    ]

    paths = {
        "events": directory / "events.csv",
        "summaries": directory / "daily_summary.csv",
        "heartbeats": directory / "ingestion_heartbeats.csv",
    }
    _write(paths["events"], ["event_id", "ticket_id", "team", "occurred_at", "event_type", "work_minutes"], [
        dict(zip(("event_id", "ticket_id", "team", "occurred_at", "event_type", "work_minutes"), row))
        for row in events
    ])
    _write(paths["summaries"], ["day", "team", "event_count", "work_minutes", "generated_at"], [
        dict(zip(("day", "team", "event_count", "work_minutes", "generated_at"), row))
        for row in summary
    ])
    _write(paths["heartbeats"], ["team", "last_successful_ingestion_at"], [
        dict(zip(("team", "last_successful_ingestion_at"), row))
        for row in heartbeats
    ])
    return paths


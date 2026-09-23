"""Validate event feeds, reconcile them in SQLite, and emit reviewable evidence."""

import csv
import sqlite3
from datetime import date, datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path


class InputSchemaError(ValueError):
    """A required CSV column or CLI parameter is missing or malformed."""


EVENT_COLUMNS = {"event_id", "ticket_id", "team", "occurred_at", "event_type", "work_minutes"}
SUMMARY_COLUMNS = {"day", "team", "event_count", "work_minutes", "generated_at"}
HEARTBEAT_COLUMNS = {"team", "last_successful_ingestion_at"}
EVENT_TYPES = {"created", "worked", "resolved"}


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("expected ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must have a timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    # Fixed precision lets SQLite MAX(text) preserve timestamp ordering.
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _read(path: str | Path, required: set[str]) -> list[tuple[int, dict[str, str]]]:
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        if missing := required - columns:
            raise InputSchemaError(f"{path.name}: missing columns: {', '.join(sorted(missing))}")
        rows = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise InputSchemaError(f"{path.name}: row {row_number} has too many columns")
            rows.append((row_number, {key: (value or "").strip() for key, value in row.items()}))
        return rows


def _positive_int(value: str, field: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a nonnegative integer") from exc
    if number < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return number


def _issue(issues: list[dict], code: str, entity: str, reference: str, message: str) -> None:
    issues.append({"code": code, "severity": "HIGH", "entity": entity, "reference": reference, "message": message})


def reconcile(
    events: str | Path,
    summaries: str | Path,
    heartbeats: str | Path,
    *,
    as_of: str,
    freshness_minutes: int = 120,
) -> dict:
    """Return an auditable report. Invalid rows are excluded and reported."""
    try:
        clock = _utc(as_of)
    except ValueError as exc:
        raise InputSchemaError(f"as_of: {exc}") from exc
    if freshness_minutes <= 0:
        raise InputSchemaError("freshness_minutes must be greater than zero")

    event_rows = _read(events, EVENT_COLUMNS)
    summary_rows = _read(summaries, SUMMARY_COLUMNS)
    heartbeat_rows = _read(heartbeats, HEARTBEAT_COLUMNS)
    issues: list[dict] = []
    valid_events: list[tuple] = []
    valid_summaries: list[tuple] = []
    valid_heartbeats: dict[str, str] = {}

    for source_row, row in event_rows:
        try:
            for field in EVENT_COLUMNS:
                if not row[field]:
                    raise ValueError(f"{field} is required")
            if row["event_type"] not in EVENT_TYPES:
                raise ValueError(f"unknown event_type: {row['event_type']}")
            when = _utc(row["occurred_at"])
            if when > clock:
                raise ValueError("occurred_at is later than as_of")
            minutes = _positive_int(row["work_minutes"], "work_minutes")
        except ValueError as exc:
            _issue(issues, "INVALID_EVENT", "event", f"row {source_row}", str(exc))
            continue
        valid_events.append((source_row, row["event_id"], row["ticket_id"], row["team"], _iso(when), row["event_type"], minutes))

    for source_row, row in summary_rows:
        try:
            for field in SUMMARY_COLUMNS:
                if not row[field]:
                    raise ValueError(f"{field} is required")
            day = date.fromisoformat(row["day"])
            if day.isoformat() != row["day"]:
                raise ValueError("day must be YYYY-MM-DD")
            generated = _utc(row["generated_at"])
            if generated > clock:
                raise ValueError("generated_at is later than as_of")
            count = _positive_int(row["event_count"], "event_count")
            minutes = _positive_int(row["work_minutes"], "work_minutes")
        except ValueError as exc:
            _issue(issues, "INVALID_SUMMARY", "summary", f"row {source_row}", str(exc))
            continue
        valid_summaries.append((source_row, row["day"], row["team"], count, minutes, _iso(generated)))

    for source_row, row in heartbeat_rows:
        try:
            for field in HEARTBEAT_COLUMNS:
                if not row[field]:
                    raise ValueError(f"{field} is required")
            seen = _utc(row["last_successful_ingestion_at"])
            if seen > clock:
                raise ValueError("last_successful_ingestion_at is later than as_of")
        except ValueError as exc:
            _issue(issues, "INVALID_HEARTBEAT", "heartbeat", f"row {source_row}", str(exc))
            continue
        team = row["team"]
        if team in valid_heartbeats:
            _issue(issues, "DUPLICATE_HEARTBEAT", "heartbeat", team, "multiple ingestion heartbeats for one team")
            continue
        valid_heartbeats[team] = _iso(seen)

    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE valid_events (
                source_row INTEGER PRIMARY KEY, event_id TEXT NOT NULL, ticket_id TEXT NOT NULL,
                team TEXT NOT NULL, occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL, work_minutes INTEGER NOT NULL
            );
            CREATE TABLE valid_summaries (
                source_row INTEGER PRIMARY KEY, day TEXT NOT NULL, team TEXT NOT NULL,
                event_count INTEGER NOT NULL, work_minutes INTEGER NOT NULL,
                generated_at TEXT NOT NULL
            );
        """)
        connection.executemany("INSERT INTO valid_events VALUES (?, ?, ?, ?, ?, ?, ?)", valid_events)
        connection.executemany("INSERT INTO valid_summaries VALUES (?, ?, ?, ?, ?, ?)", valid_summaries)

        duplicates = connection.execute("""
            SELECT event_id, COUNT(*) AS occurrences FROM valid_events
            GROUP BY event_id HAVING COUNT(*) > 1 ORDER BY event_id
        """).fetchall()
        for duplicate in duplicates:
            _issue(issues, "DUPLICATE_EVENT_ID", "event", duplicate["event_id"],
                   f"{duplicate['occurrences']} valid source rows share this event_id; first row retained")

        duplicate_summaries = connection.execute("""
            SELECT day, team, COUNT(*) AS occurrences FROM valid_summaries
            GROUP BY day, team HAVING COUNT(*) > 1 ORDER BY day, team
        """).fetchall()
        for duplicate in duplicate_summaries:
            _issue(issues, "DUPLICATE_SUMMARY", "summary", f"{duplicate['day']}/{duplicate['team']}",
                   f"{duplicate['occurrences']} summary rows share this key; first row retained")

        statement = files("ops_recon").joinpath("reconciliation.sql").read_text(encoding="utf-8")
        comparison = connection.execute(statement).fetchall()

    partitions: list[dict] = []
    for row in comparison:
        day, team = row["day"], row["team"]
        ref = f"{day}/{team}"
        actual_count, reported_count = row["actual_count"], row["reported_count"]
        actual_minutes, reported_minutes = row["actual_minutes"], row["reported_minutes"]
        if actual_count is None:
            status = "ORPHAN_SUMMARY"
            _issue(issues, "ORPHAN_SUMMARY", "partition", ref, "summary exists without canonical source events")
        elif reported_count is None:
            status = "MISSING_SUMMARY"
            _issue(issues, "MISSING_SUMMARY", "partition", ref, "canonical source events have no daily summary")
        elif actual_count != reported_count or actual_minutes != reported_minutes:
            status = "MISMATCH"
            _issue(issues, "RECON_MISMATCH", "partition", ref, "event count and/or work minutes disagree")
        else:
            status = "MATCH"
        if row["latest_event_at"] and row["generated_at"] and row["generated_at"] < row["latest_event_at"]:
            _issue(issues, "STALE_SUMMARY", "partition", ref, "summary was produced before its latest source event")
        partitions.append({
            "day": day, "team": team, "status": status,
            "actual_event_count": actual_count, "reported_event_count": reported_count,
            "event_count_delta": actual_count - reported_count if actual_count is not None and reported_count is not None else None,
            "actual_work_minutes": actual_minutes, "reported_work_minutes": reported_minutes,
            "work_minutes_delta": actual_minutes - reported_minutes if actual_minutes is not None and reported_minutes is not None else None,
        })

    for team in sorted({row["team"] for row in comparison if row["actual_count"] is not None}):
        seen = valid_heartbeats.get(team)
        if seen is None:
            _issue(issues, "MISSING_HEARTBEAT", "heartbeat", team, "source team has no successful ingestion heartbeat")
        elif clock - _utc(seen) > timedelta(minutes=freshness_minutes):
            _issue(issues, "STALE_HEARTBEAT", "heartbeat", team,
                   f"last successful ingestion exceeds {freshness_minutes} minutes")

    duplicate_rows = sum(row["occurrences"] - 1 for row in duplicates)
    return {
        "scenario": "synthetic_service_operations",
        "as_of": _iso(clock),
        "freshness_minutes": freshness_minutes,
        "status": "FAIL" if issues else "PASS",
        "metrics": {
            "raw_event_rows": len(event_rows),
            "valid_event_rows": len(valid_events),
            "excluded_invalid_event_rows": len(event_rows) - len(valid_events),
            "excluded_duplicate_event_rows": duplicate_rows,
            "canonical_events": len(valid_events) - duplicate_rows,
            "total_partitions": len(partitions),
            "matched_partitions": sum(row["status"] == "MATCH" for row in partitions),
            "issue_count": len(issues),
        },
        "partitions": partitions,
        "issues": issues,
    }


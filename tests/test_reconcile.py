import csv
import json
import tempfile
import unittest
from pathlib import Path

from ops_recon.cli import main
from ops_recon.generator import AS_OF, generate_fixture
from ops_recon.reconcile import InputSchemaError, reconcile


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _save(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class ReconciliationTests(unittest.TestCase):
    def test_seeded_failures_have_evidence_without_double_counting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = generate_fixture(directory)
            report = reconcile(**paths, as_of=AS_OF)

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["metrics"], {
            "raw_event_rows": 11, "valid_event_rows": 10,
            "excluded_invalid_event_rows": 1, "excluded_duplicate_event_rows": 1,
            "canonical_events": 9, "total_partitions": 5,
            "matched_partitions": 2, "issue_count": 7,
        })
        north = next(row for row in report["partitions"] if row["team"] == "North")
        self.assertEqual((north["status"], north["actual_event_count"], north["event_count_delta"], north["work_minutes_delta"]),
                         ("MISMATCH", 4, 1, 15))
        self.assertEqual({row["team"]: row["status"] for row in report["partitions"]}, {
            "Central": "MATCH", "East": "ORPHAN_SUMMARY", "North": "MISMATCH",
            "South": "MATCH", "West": "MISSING_SUMMARY",
        })
        self.assertEqual({issue["code"] for issue in report["issues"]}, {
            "INVALID_EVENT", "DUPLICATE_EVENT_ID", "RECON_MISMATCH",
            "STALE_SUMMARY", "MISSING_SUMMARY", "ORPHAN_SUMMARY", "STALE_HEARTBEAT",
        })

    def test_clean_control_passes_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = generate_fixture(directory, clean=True)
            report = reconcile(**paths, as_of=AS_OF)
            second = reconcile(**paths, as_of=AS_OF)

        self.assertEqual(report, second)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["metrics"]["canonical_events"], 9)
        self.assertEqual(report["metrics"]["matched_partitions"], 4)
        self.assertEqual(report["issues"], [])

    def test_missing_heartbeat_is_reported_for_active_team(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = generate_fixture(directory, clean=True)
            _save(paths["heartbeats"], [row for row in _rows(paths["heartbeats"]) if row["team"] != "West"])
            report = reconcile(**paths, as_of=AS_OF)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn({"code": "MISSING_HEARTBEAT", "severity": "HIGH", "entity": "heartbeat",
                       "reference": "West", "message": "source team has no successful ingestion heartbeat"}, report["issues"])

    def test_invalid_values_are_excluded_and_labeled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = generate_fixture(directory, clean=True)
            rows = _rows(paths["events"])
            rows.append({**rows[0], "event_id": "BAD-01", "occurred_at": "2026-09-24T11:00:00Z"})
            rows.append({**rows[0], "event_id": "BAD-02", "work_minutes": "-2"})
            _save(paths["events"], rows)
            report = reconcile(**paths, as_of=AS_OF)

        self.assertEqual(report["metrics"]["excluded_invalid_event_rows"], 2)
        self.assertEqual(report["metrics"]["canonical_events"], 9)
        self.assertEqual([issue["code"] for issue in report["issues"]], ["INVALID_EVENT", "INVALID_EVENT"])

    def test_missing_column_has_explicit_schema_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = generate_fixture(directory, clean=True)
            paths["events"].write_text("event_id,team\nEV-1,North\n", encoding="utf-8")
            with self.assertRaisesRegex(InputSchemaError, "missing columns"):
                reconcile(**paths, as_of=AS_OF)

    def test_strict_cli_blocks_anomalies_and_allows_clean_control(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad"
            good = Path(directory) / "good"
            self.assertEqual(main(["demo", "--output-dir", str(bad), "--strict"]), 2)
            self.assertEqual(main(["demo", "--output-dir", str(good), "--clean", "--strict"]), 0)
            self.assertEqual(json.loads((bad / "report.json").read_text())["status"], "FAIL")
            self.assertEqual(json.loads((good / "report.json").read_text())["status"], "PASS")


if __name__ == "__main__":
    unittest.main()


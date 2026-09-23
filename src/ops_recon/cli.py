"""Command-line interface for reproducible demonstration and CSV inputs."""

import argparse
import json
import sys
from pathlib import Path

from .generator import AS_OF, generate_fixture
from .reconcile import InputSchemaError, reconcile


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reconcile synthetic operational events with daily summaries")
    commands = parser.add_subparsers(dest="command", required=True)

    demo = commands.add_parser("demo", help="Generate and analyze deterministic sample data")
    demo.add_argument("--output-dir", type=Path, default=Path("recon-output"))
    demo.add_argument("--clean", action="store_true", help="Generate a passing control scenario")
    demo.add_argument("--strict", action="store_true", help="Exit 2 when the report fails")

    run = commands.add_parser("run", help="Analyze three existing CSV inputs")
    run.add_argument("--events", type=Path, required=True)
    run.add_argument("--summaries", type=Path, required=True)
    run.add_argument("--heartbeats", type=Path, required=True)
    run.add_argument("--as-of", required=True, help="ISO 8601 timestamp with UTC offset")
    run.add_argument("--freshness-minutes", type=int, default=120)
    run.add_argument("--output", type=Path, default=Path("recon-output/report.json"))
    run.add_argument("--strict", action="store_true", help="Exit 2 when the report fails")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "demo":
        paths = generate_fixture(args.output_dir, clean=args.clean)
        events, summaries, heartbeats = paths["events"], paths["summaries"], paths["heartbeats"]
        as_of, freshness_minutes = AS_OF, 120
        output = args.output_dir / "report.json"
    else:
        events, summaries, heartbeats = args.events, args.summaries, args.heartbeats
        as_of, freshness_minutes = args.as_of, args.freshness_minutes
        output = args.output

    try:
        report = reconcile(events, summaries, heartbeats, as_of=as_of, freshness_minutes=freshness_minutes)
    except (InputSchemaError, FileNotFoundError, PermissionError) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    metrics = report["metrics"]
    print(f"Gate: {report['status']} | {metrics['canonical_events']} canonical events "
          f"| {metrics['matched_partitions']}/{metrics['total_partitions']} matched partitions "
          f"| {metrics['issue_count']} issues")
    for row in report["partitions"]:
        print(f"  {row['day']} {row['team']:<8} {row['status']:<16} "
              f"events={row['actual_event_count']}/{row['reported_event_count']} "
              f"minutes={row['actual_work_minutes']}/{row['reported_work_minutes']}")
    print(f"Report: {output.resolve()}")
    return 2 if args.strict and report["status"] == "FAIL" else 0


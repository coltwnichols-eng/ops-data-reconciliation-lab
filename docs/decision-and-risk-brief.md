# Decision and risk brief

**Scenario:** entirely invented service-ticket event feed and daily operational summary. **Evaluation time:** 2026-09-23 12:00 UTC. **Result:** FAIL, 7 high-severity issues; 2 of 5 day/team partitions match. This is a worked example of how I would turn technical findings into accountable decisions.

## Program decision

**Hold any downstream use of the seeded summary.** North's reported count and work minutes are lower than the canonical event view; West and East indicate missing/orphan partitions; Central's ingestion health cannot be trusted at the configured threshold. Data engineering should reproduce, correct, backfill, and rerun the gate. An operations owner should approve the reconciled counts before the summary is released. These are *illustrative roles*, not real assignments.

## Evidence to action

| Signal | Impact | Example owner | Next check / decision |
| --- | --- | --- | --- |
| North: 4 / 70 actual vs 3 / 55 reported; summary predates latest event | Underreported activity | Data engineering | Verify snapshot cutoff; rebuild partition; compare after replay |
| West events without a daily summary | Missing reporting coverage | Pipeline owner | Inspect partition creation and scheduler logs; backfill |
| East summary without source events | Unexplained reporting record | Source owner | Identify legitimate correction versus orphan; quarantine until explained |
| Central heartbeat older than 120 minutes | Ingestion health unknown | Platform owner | Verify last successful run, error logs, and recovery watermark |
| One invalid row without a ticket ID | Potential lost activity | Source owner | Repair record and rerun; inspect producer contract |
| Repeated event ID | Potential double count | Producer owner | Confirm retry/idempotency behavior; deduplication is temporary containment |

## Decision log

| ID | Design decision in this demo | Reason / remaining production question |
| --- | --- | --- |
| D-01 | Event ID is the canonical event key; first valid source row is retained for totals. | Demonstrates deterministic aggregation. Production must define how to resolve conflicting payloads sharing an ID. |
| D-02 | Aggregate by UTC day and team. | Prevents silent timezone mixing. Production must define the business day and daylight-saving behavior. |
| D-03 | Use last **successful ingestion heartbeat** for freshness, with a 120-minute sample threshold. | Event timestamps cannot prove a quiet team is stale. The threshold needs a real SLA and monitoring owner. |
| D-04 | Treat an output produced before its latest event as stale. | The demo exposes late arrival; production needs an explicit allowed lag or watermark. |
| D-05 | Any issue fails the strict gate; the example assigns all findings HIGH. | Conservative for a release gate. Production needs tiered severity, incident routing, and formally approved tolerances. |

## Risk register

| Risk | Trigger / evidence | Mitigation and proof of closure |
| --- | --- | --- |
| Incorrect operational totals | Day/team count or minute delta | Recompute from canonical events, reconcile at the same cutoff, obtain operations signoff |
| Missing or orphaned partitions | Source key absent from summary or vice versa | Inspect job logs and partition keys, repair or backfill, rerun full key-space comparison |
| Delayed pipeline | Missing or stale success heartbeat | Alert against owner-approved SLA; verify successful run and watermark advancement |
| Duplicate delivery or conflicting correction | Reused event ID | Enforce idempotency at source; quarantine conflicting payloads; retain raw audit record |
| Invalid source record | Missing required field or malformed value | Preserve raw row reference, route to producer, repair source, rerun from raw input |
| Bad release decision | Summary released despite open HIGH issue | Make reconciled report a mandatory gate with named approval and retained evidence |

## Production handoff questions

1. Which source owns each event and when can an event be corrected or deleted?
2. What is the accepted late-arrival window and the authoritative business-day timezone?
3. Which teams and day partitions must exist even when there are zero events?
4. Who owns retries, alert routing, exception closure, and signoff?
5. What are the exact data latency and reconciliation thresholds for blocking downstream use?
6. How are source counts, ingestion watermarks, backfills, and approval evidence retained for audit?

**Limits:** The fixture is tiny; the engine reads CSVs into an in-memory SQLite database and is not a scale benchmark. It models one snapshot per day/team and one heartbeat per team, flags any duplicate as an issue, and does not implement streaming, orchestration, retries, or automated repairs.


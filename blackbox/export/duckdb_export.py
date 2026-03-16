"""Export Temporal workflow histories to DuckDB.

Single-pass approach: fetch each workflow's full event history once,
extract both the WorkflowResult (workflows table) and activity execution
details (activity_executions table).

Usage:
    from blackbox.export.duckdb_export import run_export
    summary = asyncio.run(run_export())
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import duckdb
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client

from blackbox.config import (
    DUCKDB_PATH,
    TEMPORAL_HOST,
    TEMPORAL_NAMESPACE,
    TEMPORAL_TASK_QUEUE,
)

logger = logging.getLogger(__name__)

MAX_CONCURRENT_FETCHES = 50

WORKFLOW_COLUMNS = [
    "workflow_id",
    "order_id",
    "user_id",
    "model_version",
    "cohort",
    "decision",
    "fraud_score",
    "amount",
    "shipping_country",
    "billing_country",
    "timestamp",
    "reason_codes",
]

ACTIVITY_COLUMNS = [
    "workflow_id",
    "activity_type",
    "inputs",
    "outputs",
    "duration_ms",
    "retry_count",
    "scheduled_time",
    "completed_time",
]

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_WORKFLOWS = """
CREATE TABLE IF NOT EXISTS workflows (
    workflow_id       VARCHAR PRIMARY KEY,
    order_id          VARCHAR NOT NULL,
    user_id           VARCHAR NOT NULL,
    model_version     VARCHAR NOT NULL,
    cohort            INTEGER NOT NULL,
    decision          VARCHAR NOT NULL,
    fraud_score       INTEGER NOT NULL,
    amount            DOUBLE NOT NULL,
    shipping_country  VARCHAR NOT NULL,
    billing_country   VARCHAR NOT NULL,
    timestamp         TIMESTAMP NOT NULL,
    reason_codes      VARCHAR NOT NULL
);
"""

_CREATE_ACTIVITIES = """
CREATE TABLE IF NOT EXISTS activity_executions (
    workflow_id       VARCHAR NOT NULL,
    activity_type     VARCHAR NOT NULL,
    inputs            VARCHAR NOT NULL,
    outputs           VARCHAR NOT NULL,
    duration_ms       DOUBLE,
    retry_count       INTEGER NOT NULL DEFAULT 0,
    scheduled_time    TIMESTAMP,
    completed_time    TIMESTAMP,
    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
);
"""


def create_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Create the workflows and activity_executions tables (idempotent)."""
    con.execute(_CREATE_WORKFLOWS)
    con.execute(_CREATE_ACTIVITIES)


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------


def insert_workflows(con: duckdb.DuckDBPyConnection, rows: list[dict]) -> int:
    """Insert workflow rows, replacing any existing rows with the same workflow_id."""
    if not rows:
        return 0
    con.executemany(
        """INSERT OR REPLACE INTO workflows
           (workflow_id, order_id, user_id, model_version, cohort, decision,
            fraud_score, amount, shipping_country, billing_country, timestamp, reason_codes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [tuple(row[col] for col in WORKFLOW_COLUMNS) for row in rows],
    )
    return len(rows)


def insert_activity_executions(con: duckdb.DuckDBPyConnection, rows: list[dict]) -> int:
    """Insert activity execution rows. Clears existing rows first for idempotent re-export."""
    if not rows:
        return 0
    con.execute("DELETE FROM activity_executions")
    con.executemany(
        """INSERT INTO activity_executions
           (workflow_id, activity_type, inputs, outputs, duration_ms,
            retry_count, scheduled_time, completed_time)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [tuple(row[col] for col in ACTIVITY_COLUMNS) for row in rows],
    )
    return len(rows)


# ---------------------------------------------------------------------------
# History parsing
# ---------------------------------------------------------------------------


def _proto_ts_to_datetime(ts) -> datetime | None:
    """Convert a protobuf Timestamp to a Python datetime."""
    if ts is None:
        return None
    # Temporal SDK exposes event_time as google.protobuf.Timestamp
    dt = ts.ToDatetime()
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _decode_payloads(payloads) -> str:
    """Decode Temporal payloads to a JSON string."""
    if payloads is None or not payloads:
        return "[]"
    decoded = []
    for p in payloads:
        try:
            decoded.append(json.loads(p.data.decode("utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            decoded.append(p.data.hex())
    return json.dumps(decoded)


def _parse_history(
    workflow_id: str, history
) -> tuple[dict | None, list[dict]]:
    """Extract one workflow row and N activity rows from a workflow history.

    Returns (workflow_row, activity_rows).  workflow_row is None if the
    completion event isn't found (shouldn't happen for completed workflows).
    """
    workflow_row: dict | None = None
    activity_rows: list[dict] = []

    # Index scheduled and started events for correlation
    scheduled: dict[int, object] = {}  # event_id -> event
    started: dict[int, object] = {}  # scheduled_event_id -> event

    for event in history.events:
        etype = event.event_type

        if etype == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED:
            attrs = event.workflow_execution_completed_event_attributes
            if attrs.result and attrs.result.payloads:
                payload_data = json.loads(attrs.result.payloads[0].data.decode("utf-8"))
                reason_codes = payload_data.get("reason_codes", [])
                ts_str = payload_data.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    ts = None
                workflow_row = {
                    "workflow_id": workflow_id,
                    "order_id": payload_data.get("order_id", ""),
                    "user_id": payload_data.get("user_id", ""),
                    "model_version": payload_data.get("model_version", ""),
                    "cohort": payload_data.get("cohort", 0),
                    "decision": payload_data.get("decision", ""),
                    "fraud_score": payload_data.get("fraud_score", 0),
                    "amount": payload_data.get("amount", 0.0),
                    "shipping_country": payload_data.get("shipping_country", ""),
                    "billing_country": payload_data.get("billing_country", ""),
                    "timestamp": ts,
                    "reason_codes": json.dumps(reason_codes),
                }

        elif etype == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
            scheduled[event.event_id] = event

        elif etype == EventType.EVENT_TYPE_ACTIVITY_TASK_STARTED:
            attrs = event.activity_task_started_event_attributes
            started[attrs.scheduled_event_id] = event

        elif etype == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
            attrs = event.activity_task_completed_event_attributes
            sched_id = attrs.scheduled_event_id
            sched_event = scheduled.get(sched_id)
            start_event = started.get(sched_id)

            if sched_event is None:
                continue

            sched_attrs = sched_event.activity_task_scheduled_event_attributes
            activity_type = sched_attrs.activity_type.name

            inputs_str = _decode_payloads(
                sched_attrs.input.payloads if sched_attrs.input else None
            )
            outputs_str = _decode_payloads(
                attrs.result.payloads if attrs.result else None
            )

            sched_time = _proto_ts_to_datetime(sched_event.event_time)
            completed_time = _proto_ts_to_datetime(event.event_time)

            duration_ms = None
            if sched_time and completed_time:
                duration_ms = (completed_time - sched_time).total_seconds() * 1000

            retry_count = 0
            if start_event:
                start_attrs = start_event.activity_task_started_event_attributes
                retry_count = max(0, start_attrs.attempt - 1)

            activity_rows.append(
                {
                    "workflow_id": workflow_id,
                    "activity_type": activity_type,
                    "inputs": inputs_str,
                    "outputs": outputs_str,
                    "duration_ms": duration_ms,
                    "retry_count": retry_count,
                    "scheduled_time": sched_time,
                    "completed_time": completed_time,
                }
            )

    return workflow_row, activity_rows


# ---------------------------------------------------------------------------
# Temporal fetching
# ---------------------------------------------------------------------------


async def _fetch_and_parse(
    client: Client,
    workflow_id: str,
    sem: asyncio.Semaphore,
) -> tuple[dict | None, list[dict]]:
    """Fetch one workflow's history and parse it."""
    async with sem:
        handle = client.get_workflow_handle(workflow_id)
        history = await handle.fetch_history()
        return _parse_history(workflow_id, history)


async def run_export(
    db_path: str = DUCKDB_PATH,
    temporal_host: str = TEMPORAL_HOST,
    namespace: str = TEMPORAL_NAMESPACE,
    task_queue: str = TEMPORAL_TASK_QUEUE,
) -> dict:
    """Export all completed workflows from Temporal to DuckDB.

    Returns a summary dict with row counts and elapsed time.
    """
    start = time.monotonic()

    # 1. Connect to Temporal
    logger.info("Connecting to Temporal at %s (namespace=%s)", temporal_host, namespace)
    client = await Client.connect(temporal_host, namespace=namespace)

    # 2. List completed workflows
    logger.info("Listing completed workflows on queue %s...", task_queue)
    workflow_ids: list[str] = []
    async for wf in client.list_workflows(
        f'TaskQueue="{task_queue}" AND ExecutionStatus="Completed"'
    ):
        workflow_ids.append(wf.id)

    logger.info("Found %d completed workflows", len(workflow_ids))

    if not workflow_ids:
        return {"workflows": 0, "activity_executions": 0, "elapsed_s": 0.0}

    # 3. Fetch histories concurrently
    sem = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    logger.info("Fetching event histories (concurrency=%d)...", MAX_CONCURRENT_FETCHES)

    tasks = [_fetch_and_parse(client, wf_id, sem) for wf_id in workflow_ids]

    wf_rows: list[dict] = []
    act_rows: list[dict] = []
    completed = 0

    for coro in asyncio.as_completed(tasks):
        wf_row, act_row_list = await coro
        if wf_row:
            wf_rows.append(wf_row)
        act_rows.extend(act_row_list)
        completed += 1
        if completed % 1000 == 0:
            logger.info("Parsed %d/%d histories...", completed, len(workflow_ids))

    logger.info("Parsed all histories: %d workflow rows, %d activity rows", len(wf_rows), len(act_rows))

    # 4. Write to DuckDB
    logger.info("Writing to DuckDB at %s...", db_path)
    con = duckdb.connect(db_path)
    try:
        create_tables(con)
        con.execute("BEGIN TRANSACTION")
        wf_count = insert_workflows(con, wf_rows)
        act_count = insert_activity_executions(con, act_rows)
        con.execute("COMMIT")

        # 5. Validation
        null_count = con.execute(
            "SELECT COUNT(*) FROM workflows WHERE order_id IS NULL OR decision IS NULL"
        ).fetchone()[0]
        if null_count > 0:
            logger.warning("Data quality issue: %d workflow rows have NULL required fields", null_count)
    finally:
        con.close()

    elapsed = time.monotonic() - start
    summary = {
        "workflows": wf_count,
        "activity_executions": act_count,
        "elapsed_s": round(elapsed, 1),
    }
    logger.info(
        "Export complete: %d workflows, %d activities in %.1fs",
        wf_count, act_count, elapsed,
    )
    return summary

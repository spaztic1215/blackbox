"""Export Temporal workflow histories to DuckDB.

Usage:
    python scripts/export_to_duckdb.py [--db-path blackbox_warehouse.duckdb]

Requires a running Temporal server with completed workflows
(run scripts/run_simulation.py first).
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from blackbox.config import DUCKDB_PATH, TEMPORAL_HOST, TEMPORAL_NAMESPACE, TEMPORAL_TASK_QUEUE
from blackbox.export.duckdb_export import run_export

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Export Temporal workflows to DuckDB")
    parser.add_argument("--db-path", default=DUCKDB_PATH, help="DuckDB file path")
    parser.add_argument("--host", default=TEMPORAL_HOST, help="Temporal host:port")
    parser.add_argument("--namespace", default=TEMPORAL_NAMESPACE, help="Temporal namespace")
    parser.add_argument("--task-queue", default=TEMPORAL_TASK_QUEUE, help="Task queue name")
    args = parser.parse_args()

    summary = await run_export(
        db_path=args.db_path,
        temporal_host=args.host,
        namespace=args.namespace,
        task_queue=args.task_queue,
    )

    print(f"\nExport summary:")
    print(f"  Workflows:          {summary['workflows']:,}")
    print(f"  Activity executions: {summary['activity_executions']:,}")
    print(f"  Elapsed:            {summary['elapsed_s']:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())

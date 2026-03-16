"""Start OrderFraudWorkflows for all generated orders.

Usage:
    python scripts/run_simulation.py [--count 10000] [--batch-size 100]

Requires a running Temporal server and worker process.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from temporalio.client import Client

from blackbox.config import TEMPORAL_HOST, TEMPORAL_NAMESPACE, TEMPORAL_TASK_QUEUE
from blackbox.utils.data_generator import generate_orders
from blackbox.workflows.order_fraud import OrderFraudWorkflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def run_simulation(count: int, batch_size: int) -> None:
    """Generate orders and submit them as Temporal workflows."""
    logger.info("Connecting to Temporal at %s", TEMPORAL_HOST)
    client = await Client.connect(TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE)

    logger.info("Generating %d synthetic orders...", count)
    orders = generate_orders(n=count)
    logger.info("Generated %d orders (first: %s, last: %s)", len(orders), orders[0].timestamp, orders[-1].timestamp)

    start = time.monotonic()
    completed = 0
    errors = 0

    for i in range(0, len(orders), batch_size):
        batch = orders[i : i + batch_size]
        handles = []

        for order in batch:
            try:
                handle = await client.start_workflow(
                    OrderFraudWorkflow.run,
                    order,
                    id=f"fraud-check-{order.order_id}",
                    task_queue=TEMPORAL_TASK_QUEUE,
                )
                handles.append(handle)
            except Exception as e:
                logger.warning("Failed to start workflow for %s: %s", order.order_id, e)
                errors += 1

        # Wait for the batch to complete
        for handle in handles:
            try:
                await handle.result()
                completed += 1
            except Exception as e:
                logger.warning("Workflow failed: %s", e)
                errors += 1

        elapsed = time.monotonic() - start
        rate = completed / elapsed if elapsed > 0 else 0
        logger.info(
            "Progress: %d/%d completed (%d errors) — %.1f wf/s",
            completed, len(orders), errors, rate,
        )

    elapsed = time.monotonic() - start
    logger.info(
        "Simulation complete: %d workflows in %.1fs (%.1f wf/s, %d errors)",
        completed, elapsed, completed / elapsed, errors,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Blackbox fraud simulation")
    parser.add_argument("--count", type=int, default=10_000, help="Number of orders")
    parser.add_argument("--batch-size", type=int, default=100, help="Workflows per batch")
    args = parser.parse_args()

    asyncio.run(run_simulation(args.count, args.batch_size))


if __name__ == "__main__":
    main()

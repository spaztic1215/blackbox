"""Temporal worker process for Blackbox.

Run this before starting any workflows:
    python -m blackbox.worker

It registers the OrderFraudWorkflow and its activities with
the Temporal server, then polls the task queue for work.
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from blackbox.activities.fraud_check import check_fraud_score
from blackbox.config import TEMPORAL_HOST, TEMPORAL_NAMESPACE, TEMPORAL_TASK_QUEUE
from blackbox.workflows.order_fraud import OrderFraudWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_worker() -> None:
    """Connect to Temporal and start the worker."""
    logger.info("Connecting to Temporal at %s (namespace=%s)", TEMPORAL_HOST, TEMPORAL_NAMESPACE)
    client = await Client.connect(TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE)

    logger.info("Starting worker on task queue: %s", TEMPORAL_TASK_QUEUE)
    worker = Worker(
        client,
        task_queue=TEMPORAL_TASK_QUEUE,
        workflows=[OrderFraudWorkflow],
        activities=[check_fraud_score],
    )
    await worker.run()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

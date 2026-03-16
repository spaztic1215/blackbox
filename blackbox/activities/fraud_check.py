"""Temporal activities for Blackbox.

Activities are the units of work that Temporal tracks with full
input/output in the Event History — this is what makes the audit
trail possible.
"""

from __future__ import annotations

import time

from temporalio import activity

from blackbox.fraud_api.scorer import score_order
from blackbox.models.data import FraudResult, Order


@activity.defn
async def check_fraud_score(order: Order, model_version: str) -> FraudResult:
    """Call the mock fraud API and return the result.

    In production this would be an HTTP call to a real fraud service.
    Temporal captures both the inputs (order + model_version) and the
    output (FraudResult) in the Event History automatically.
    """
    activity.logger.info(
        "Scoring order %s with model %s (amount=%.2f, country=%s)",
        order.order_id,
        model_version,
        order.amount,
        order.shipping_country,
    )

    start = time.monotonic()
    result = score_order(order, model_version)
    elapsed_ms = (time.monotonic() - start) * 1000

    activity.logger.info(
        "Order %s → score=%d decision=%s (%.1fms)",
        order.order_id,
        result.score,
        result.decision,
        elapsed_ms,
    )

    return result

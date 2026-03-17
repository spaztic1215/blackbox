"""OrderFraudWorkflow — core Temporal workflow for Blackbox.

Each order goes through this workflow which:
1. Assigns a model version via hash-based gradual rollout
2. Executes the fraud-check activity
3. Records search attributes for Temporal Visibility queries
4. Returns a complete WorkflowResult for the audit trail
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from temporalio import workflow
from temporalio.common import SearchAttributeKey, SearchAttributePair, TypedSearchAttributes

with workflow.unsafe.imports_passed_through():
    from blackbox.config import (
        BASELINE_END,
        CANARY_END,
        CANARY_PERCENT,
        MODEL_VERSION_NEW,
        MODEL_VERSION_OLD,
        ROLLOUT_END,
        ROLLOUT_PERCENT,
    )
    from blackbox.models.data import FraudResult, Order, WorkflowResult


# ---------------------------------------------------------------------------
# Search attribute keys  (must be registered in the Temporal server)
# ---------------------------------------------------------------------------
SA_MODEL_VERSION = SearchAttributeKey.for_keyword("BlackboxModelVersion")
SA_DECISION = SearchAttributeKey.for_keyword("BlackboxDecision")
SA_FRAUD_SCORE = SearchAttributeKey.for_int("BlackboxFraudScore")
SA_USER_COHORT = SearchAttributeKey.for_int("BlackboxUserCohort")
SA_SHIPPING_COUNTRY = SearchAttributeKey.for_keyword("BlackboxShippingCountry")
SA_ORDER_AMOUNT = SearchAttributeKey.for_float("BlackboxOrderAmount")


@workflow.defn
class OrderFraudWorkflow:
    """Process a single order through fraud scoring.

    The workflow is intentionally simple — one activity call — because
    the value comes from Temporal's automatic Event History capture,
    search attributes, and the ability to replay/query later.
    """

    def __init__(self) -> None:
        self._result: WorkflowResult | None = None

    @workflow.run
    async def run(self, order: Order) -> WorkflowResult:
        # 1. Determine model version via gradual rollout
        cohort = _user_cohort(order.user_id)
        model_version = _assign_version(order.timestamp, cohort)

        # 2. Execute fraud-check activity
        #    Temporal records inputs + outputs in Event History
        fraud_result: FraudResult = await workflow.execute_activity(
            "check_fraud_score",
            args=[order, model_version],
            start_to_close_timeout=timedelta(seconds=30),
            result_type=FraudResult,
        )

        # 3. Build the complete result
        result = WorkflowResult(
            order_id=order.order_id,
            user_id=order.user_id,
            amount=order.amount,
            shipping_country=order.shipping_country,
            billing_country=order.billing_country,
            timestamp=order.timestamp,
            model_version=model_version,
            cohort=cohort,
            fraud_score=fraud_result.score,
            decision=fraud_result.decision,
            reason_codes=fraud_result.reason_codes,
        )
        self._result = result

        # 4. Upsert search attributes so Visibility API queries work
        workflow.upsert_search_attributes(
            [
                SearchAttributePair(SA_MODEL_VERSION, model_version),
                SearchAttributePair(SA_DECISION, fraud_result.decision),
                SearchAttributePair(SA_FRAUD_SCORE, fraud_result.score),
                SearchAttributePair(SA_USER_COHORT, cohort),
                SearchAttributePair(SA_SHIPPING_COUNTRY, order.shipping_country),
                SearchAttributePair(SA_ORDER_AMOUNT, order.amount),
            ]
        )

        return result

    @workflow.query
    def get_result(self) -> WorkflowResult | None:
        """Query handler — lets callers inspect the result without
        waiting for workflow completion."""
        return self._result


# ---------------------------------------------------------------------------
# Rollout logic  (deterministic — same user always gets same version on same day)
# ---------------------------------------------------------------------------

def _user_cohort(user_id: str) -> int:
    """Stable hash-based cohort assignment (0-99).

    Using Python's built-in hash is fine for a demo; in production
    you'd use something like mmh3 for consistency across processes.
    We use a simple sum-of-bytes approach for determinism across runs.
    """
    return sum(user_id.encode("utf-8")) % 100


def _assign_version(timestamp_iso: str, cohort: int) -> str:
    """Determine model version based on rollout schedule + user cohort.

    Schedule (from config):
      Days 1-2:  100% v2.4.0  (baseline)
      Day 3:      10% v2.4.1  (canary)
      Days 4-5:   50% v2.4.1  (rollout)
      Days 6-7:  100% v2.4.1  (full)
    """
    order_date = datetime.fromisoformat(timestamp_iso)
    # Ensure timezone-aware comparison
    if order_date.tzinfo is None:
        order_date = order_date.replace(tzinfo=timezone.utc)

    if order_date < BASELINE_END:
        return MODEL_VERSION_OLD

    if order_date < CANARY_END:
        return MODEL_VERSION_NEW if cohort < CANARY_PERCENT else MODEL_VERSION_OLD

    if order_date < ROLLOUT_END:
        return MODEL_VERSION_NEW if cohort < ROLLOUT_PERCENT else MODEL_VERSION_OLD

    # After ROLLOUT_END → 100% new version
    return MODEL_VERSION_NEW

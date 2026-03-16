"""Mock fraud-scoring API.

Two model versions with intentionally different sensitivity to
user velocity. This is the root cause the AI agent should discover.

v2.4.0 — baseline, ~8% decline rate
v2.4.1 — 3× velocity penalty, ~16% decline rate (especially on repeat buyers)
"""

from __future__ import annotations

from blackbox.config import (
    BASE_SCORE,
    FRAUD_SCORE_THRESHOLD,
    V240_AMOUNT_THRESHOLDS,
    V240_COUNTRY_MISMATCH_PENALTY,
    V240_VELOCITY_MULTIPLIER,
    V241_AMOUNT_THRESHOLDS,
    V241_COUNTRY_MISMATCH_PENALTY,
    V241_INTERNATIONAL_PENALTY,
    V241_VELOCITY_MULTIPLIER,
)
from blackbox.models.data import FraudResult, Order


def score_order(order: Order, model_version: str) -> FraudResult:
    """Evaluate an order against the specified fraud model version.

    Returns a fully-populated FraudResult with score breakdown so the
    audit trail captures *why* a decision was made.
    """
    score = BASE_SCORE
    reasons: list[str] = []
    factors: dict[str, int] = {"base": BASE_SCORE}

    if model_version == "v2.4.0":
        score, reasons, factors = _score_v240(order, score, reasons, factors)
    elif model_version == "v2.4.1":
        score, reasons, factors = _score_v241(order, score, reasons, factors)
    else:
        raise ValueError(f"Unknown model version: {model_version}")

    # Clamp to 0-100
    score = max(0, min(100, score))

    decision = "decline" if score >= FRAUD_SCORE_THRESHOLD else "approve"

    return FraudResult(
        score=score,
        decision=decision,
        model_version=model_version,
        reason_codes=reasons,
        threshold=FRAUD_SCORE_THRESHOLD,
        raw_factors=factors,
    )


# ---------------------------------------------------------------------------
# v2.4.0  — production baseline
# ---------------------------------------------------------------------------

def _score_v240(
    order: Order,
    score: int,
    reasons: list[str],
    factors: dict[str, int],
) -> tuple[int, list[str], dict[str, int]]:
    # Velocity
    velocity_penalty = order.user_order_count_24h * V240_VELOCITY_MULTIPLIER
    if velocity_penalty > 0:
        score += velocity_penalty
        reasons.append("velocity_check")
        factors["velocity"] = velocity_penalty

    # High-value order
    amount_penalty = _amount_penalty(order.amount, V240_AMOUNT_THRESHOLDS)
    if amount_penalty > 0:
        score += amount_penalty
        reasons.append("high_value")
        factors["amount"] = amount_penalty

    # Billing/shipping country mismatch
    if order.billing_country != order.shipping_country:
        score += V240_COUNTRY_MISMATCH_PENALTY
        reasons.append("country_mismatch")
        factors["country_mismatch"] = V240_COUNTRY_MISMATCH_PENALTY

    return score, reasons, factors


# ---------------------------------------------------------------------------
# v2.4.1  — new model (root cause of the spike)
# ---------------------------------------------------------------------------

def _score_v241(
    order: Order,
    score: int,
    reasons: list[str],
    factors: dict[str, int],
) -> tuple[int, list[str], dict[str, int]]:
    # Velocity — 3× more aggressive (THIS is the root cause)
    velocity_penalty = order.user_order_count_24h * V241_VELOCITY_MULTIPLIER
    if velocity_penalty > 0:
        score += velocity_penalty
        reasons.append("velocity_check_v2")
        factors["velocity"] = velocity_penalty

    # High-value order (slightly more aggressive)
    amount_penalty = _amount_penalty(order.amount, V241_AMOUNT_THRESHOLDS)
    if amount_penalty > 0:
        score += amount_penalty
        reasons.append("high_value")
        factors["amount"] = amount_penalty

    # Billing/shipping country mismatch
    if order.billing_country != order.shipping_country:
        score += V241_COUNTRY_MISMATCH_PENALTY
        reasons.append("country_mismatch")
        factors["country_mismatch"] = V241_COUNTRY_MISMATCH_PENALTY

    # NEW in v2.4.1: international shipping penalty
    if order.shipping_country != "US":
        score += V241_INTERNATIONAL_PENALTY
        reasons.append("international_shipping")
        factors["international"] = V241_INTERNATIONAL_PENALTY

    return score, reasons, factors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _amount_penalty(amount: float, thresholds: list[tuple[int, int]]) -> int:
    """Step-function penalty based on order amount."""
    penalty = 0
    for threshold_amount, threshold_penalty in thresholds:
        if amount >= threshold_amount:
            penalty += threshold_penalty  # accumulate all matching tiers
    return penalty

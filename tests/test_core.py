"""Tests for Blackbox core components.

Run with:  pytest tests/
"""

from __future__ import annotations

import json

import duckdb

from blackbox.config import (
    BASELINE_END,
    CANARY_END,
    FRAUD_SCORE_THRESHOLD,
    ROLLOUT_BASE_DATE,
    ROLLOUT_END,
)
from blackbox.fraud_api.scorer import score_order
from blackbox.models.data import Order
from blackbox.utils.data_generator import generate_orders
from blackbox.workflows.order_fraud import _assign_version, _user_cohort


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

def test_order_creation():
    order = Order(
        order_id="test-001",
        user_id="user-abc",
        amount=99.99,
        shipping_country="US",
        billing_country="US",
        timestamp="2025-01-14T12:00:00+00:00",
    )
    assert order.order_id == "test-001"
    assert order.parsed_timestamp.year == 2025


# ---------------------------------------------------------------------------
# Fraud scoring
# ---------------------------------------------------------------------------

def _make_order(**kwargs) -> Order:
    defaults = dict(
        order_id="test-001",
        user_id="user-abc",
        amount=50.0,
        shipping_country="US",
        billing_country="US",
        timestamp="2025-01-14T12:00:00+00:00",
        user_order_count_24h=0,
    )
    defaults.update(kwargs)
    return Order(**defaults)


def test_v240_low_risk_approves():
    order = _make_order(amount=50.0, user_order_count_24h=0)
    result = score_order(order, "v2.4.0")
    assert result.decision == "approve"
    assert result.score < FRAUD_SCORE_THRESHOLD


def test_v241_velocity_causes_decline():
    """High velocity on v2.4.1 should trigger a decline that v2.4.0 wouldn't."""
    order = _make_order(amount=150.0, user_order_count_24h=3)
    result_old = score_order(order, "v2.4.0")
    result_new = score_order(order, "v2.4.1")

    # v2.4.0: base(20) + velocity(3*5=15) = 35 → approve
    assert result_old.decision == "approve"
    # v2.4.1: base(20) + velocity(3*15=45) = 65 → decline
    assert result_new.decision == "decline"
    assert result_new.score > result_old.score


def test_v241_international_penalty():
    order = _make_order(shipping_country="GB", billing_country="GB")
    result_old = score_order(order, "v2.4.0")
    result_new = score_order(order, "v2.4.1")
    # v2.4.1 adds international penalty, v2.4.0 does not
    assert result_new.score > result_old.score
    assert "international_shipping" in result_new.reason_codes
    assert "international_shipping" not in result_old.reason_codes


def test_country_mismatch():
    order = _make_order(shipping_country="US", billing_country="CA")
    result = score_order(order, "v2.4.0")
    assert "country_mismatch" in result.reason_codes


def test_high_value_penalty():
    order = _make_order(amount=1500.0)
    result = score_order(order, "v2.4.0")
    assert "high_value" in result.reason_codes
    assert result.score > 40  # base + amount penalty


# ---------------------------------------------------------------------------
# Rollout logic
# ---------------------------------------------------------------------------

def test_user_cohort_deterministic():
    assert _user_cohort("user-abc") == _user_cohort("user-abc")


def test_user_cohort_range():
    for uid in ["a", "b", "c", "hello", "test-user-123"]:
        assert 0 <= _user_cohort(uid) < 100


def test_baseline_always_old():
    ts = ROLLOUT_BASE_DATE.isoformat()
    # Every cohort should get old version during baseline
    for cohort in range(100):
        assert _assign_version(ts, cohort) == "v2.4.0"


def test_canary_10_percent():
    ts = (BASELINE_END.isoformat())  # start of canary window
    new_count = sum(1 for c in range(100) if _assign_version(ts, c) == "v2.4.1")
    assert new_count == 10  # exactly 10% (cohorts 0-9)


def test_rollout_50_percent():
    ts = CANARY_END.isoformat()  # start of 50% rollout
    new_count = sum(1 for c in range(100) if _assign_version(ts, c) == "v2.4.1")
    assert new_count == 50


def test_full_rollout_all_new():
    ts = ROLLOUT_END.isoformat()  # after rollout window
    for cohort in range(100):
        assert _assign_version(ts, cohort) == "v2.4.1"


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def test_generate_orders():
    orders = generate_orders(n=100)
    assert 50 <= len(orders) <= 100  # segment-based generator may produce fewer
    # Should be sorted by timestamp
    timestamps = [o.timestamp for o in orders]
    assert timestamps == sorted(timestamps)
    # All orders should have valid fields
    for o in orders:
        assert o.order_id.startswith("order-")
        assert o.amount > 0
        assert len(o.shipping_country) == 2


def test_velocity_is_per_day():
    """Velocity should reflect same-day orders, not a global counter."""
    orders = generate_orders(n=2000)
    for o in orders:
        assert o.user_order_count_24h >= 1  # at least this order itself


def test_velocity_distribution_has_repeat_buyers():
    """We need enough velocity >= 3 orders to produce the v2.4.1 spike."""
    orders = generate_orders(n=5000)
    high_velocity = sum(1 for o in orders if o.user_order_count_24h >= 3)
    # Need at least 5% high-velocity to see a meaningful signal
    assert high_velocity / len(orders) > 0.05, (
        f"Only {high_velocity/len(orders)*100:.1f}% high-velocity orders, need >5%"
    )


def test_decline_rate_differential():
    """v2.4.1 should produce meaningfully higher decline rate than v2.4.0."""
    from blackbox.fraud_api.scorer import score_order

    orders = generate_orders(n=5000)
    declines_v240 = sum(1 for o in orders if score_order(o, "v2.4.0").decision == "decline")
    declines_v241 = sum(1 for o in orders if score_order(o, "v2.4.1").decision == "decline")

    rate_v240 = declines_v240 / len(orders)
    rate_v241 = declines_v241 / len(orders)

    # v2.4.0 should be in the 5-15% range
    assert 0.03 < rate_v240 < 0.20, f"v2.4.0 decline rate {rate_v240:.1%} out of expected range"
    # v2.4.1 should be noticeably higher
    assert rate_v241 > rate_v240 * 1.3, (
        f"v2.4.1 ({rate_v241:.1%}) not sufficiently higher than v2.4.0 ({rate_v240:.1%})"
    )


def test_unique_users():
    """Should have a realistic number of unique users."""
    orders = generate_orders(n=5000)
    unique_users = len(set(o.user_id for o in orders))
    # Expect roughly 1500-4000 unique users for 5000 orders
    assert 500 < unique_users < 5000, f"Got {unique_users} unique users, expected 500-5000"


# ---------------------------------------------------------------------------
# DuckDB export
# ---------------------------------------------------------------------------

from blackbox.export.duckdb_export import (
    create_tables,
    insert_activity_executions,
    insert_workflows,
)


def _make_workflow_row(**kwargs) -> dict:
    from datetime import datetime, timezone
    defaults = {
        "workflow_id": "fraud-check-order-00001",
        "order_id": "order-00001",
        "user_id": "user-abc",
        "model_version": "v2.4.0",
        "cohort": 42,
        "decision": "approve",
        "fraud_score": 35,
        "amount": 99.99,
        "shipping_country": "US",
        "billing_country": "US",
        "timestamp": datetime(2025, 1, 14, 12, 0, 0, tzinfo=timezone.utc),
        "reason_codes": '["high_value"]',
    }
    defaults.update(kwargs)
    return defaults


def _make_activity_row(**kwargs) -> dict:
    from datetime import datetime, timezone
    defaults = {
        "workflow_id": "fraud-check-order-00001",
        "activity_type": "check_fraud_score",
        "inputs": '[{"order_id": "order-00001"}]',
        "outputs": '[{"score": 35, "decision": "approve"}]',
        "duration_ms": 12.5,
        "retry_count": 0,
        "scheduled_time": datetime(2025, 1, 14, 12, 0, 0, tzinfo=timezone.utc),
        "completed_time": datetime(2025, 1, 14, 12, 0, 0, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    return defaults


def test_create_tables():
    con = duckdb.connect(":memory:")
    create_tables(con)
    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    assert "workflows" in tables
    assert "activity_executions" in tables
    con.close()


def test_insert_workflows():
    con = duckdb.connect(":memory:")
    create_tables(con)
    rows = [_make_workflow_row(workflow_id=f"wf-{i}", order_id=f"order-{i}") for i in range(5)]
    count = insert_workflows(con, rows)
    assert count == 5
    db_count = con.execute("SELECT COUNT(*) FROM workflows").fetchone()[0]
    assert db_count == 5
    # Spot-check a value
    row = con.execute("SELECT decision FROM workflows WHERE workflow_id = 'wf-0'").fetchone()
    assert row[0] == "approve"
    con.close()


def test_insert_activity_executions():
    con = duckdb.connect(":memory:")
    create_tables(con)
    # Need a workflow row first for FK
    insert_workflows(con, [_make_workflow_row()])
    rows = [_make_activity_row() for _ in range(3)]
    count = insert_activity_executions(con, rows)
    assert count == 3
    db_count = con.execute("SELECT COUNT(*) FROM activity_executions").fetchone()[0]
    assert db_count == 3
    con.close()


def test_workflow_no_required_nulls():
    con = duckdb.connect(":memory:")
    create_tables(con)
    insert_workflows(con, [_make_workflow_row()])
    null_count = con.execute(
        "SELECT COUNT(*) FROM workflows WHERE order_id IS NULL OR decision IS NULL"
    ).fetchone()[0]
    assert null_count == 0
    con.close()


def test_reason_codes_stored_as_json():
    con = duckdb.connect(":memory:")
    create_tables(con)
    codes = ["velocity_check", "high_value"]
    insert_workflows(con, [_make_workflow_row(reason_codes=json.dumps(codes))])
    stored = con.execute("SELECT reason_codes FROM workflows").fetchone()[0]
    assert json.loads(stored) == codes
    con.close()


def test_idempotent_reexport():
    con = duckdb.connect(":memory:")
    create_tables(con)
    rows = [_make_workflow_row(workflow_id=f"wf-{i}", order_id=f"order-{i}") for i in range(3)]
    insert_workflows(con, rows)
    insert_workflows(con, rows)  # second insert should replace, not duplicate
    db_count = con.execute("SELECT COUNT(*) FROM workflows").fetchone()[0]
    assert db_count == 3
    con.close()

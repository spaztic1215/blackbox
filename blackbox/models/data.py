"""Core data models for Blackbox.

These are plain dataclasses (not Pydantic) because Temporal's Python SDK
uses the `dataclasses` module for workflow/activity input serialization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Order:
    """Input to the OrderFraudWorkflow.

    Represents a single e-commerce order to be evaluated for fraud.
    """

    order_id: str
    user_id: str
    amount: float
    shipping_country: str
    billing_country: str
    timestamp: str  # ISO-8601 string — Temporal serializes this cleanly
    email: str = ""
    ip_address: str = ""
    user_order_count_24h: int = 0  # recent orders — drives velocity penalty

    @property
    def parsed_timestamp(self) -> datetime:
        return datetime.fromisoformat(self.timestamp)


@dataclass
class FraudResult:
    """Output of the fraud-scoring activity.

    Captures everything needed for auditing and investigation.
    """

    score: int  # 0-100
    decision: str  # "approve" | "decline"
    model_version: str  # "v2.4.0" | "v2.4.1"
    reason_codes: list[str] = field(default_factory=list)
    threshold: int = 60  # score >= threshold → decline
    raw_factors: dict = field(default_factory=dict)  # breakdown of scoring components


@dataclass
class WorkflowResult:
    """Complete result stored on each completed workflow.

    Combines the order metadata with fraud evaluation output
    so the AI agent / DuckDB export has a single record per workflow.
    """

    order_id: str
    user_id: str
    amount: float
    shipping_country: str
    billing_country: str
    timestamp: str
    model_version: str
    cohort: int  # hash(user_id) % 100 — for rollout assignment
    fraud_score: int
    decision: str
    reason_codes: list[str] = field(default_factory=list)
    processing_time_ms: Optional[float] = None

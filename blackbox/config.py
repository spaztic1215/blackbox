"""Global configuration for Blackbox.

All rollout dates, thresholds, and connection settings live here so
they're easy to tweak for demos or tests.
"""

from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Rollout schedule
#   Simulated 7-day window. Adjust ROLLOUT_BASE_DATE to shift everything.
# ---------------------------------------------------------------------------
ROLLOUT_BASE_DATE = datetime(2025, 1, 14, 0, 0, 0, tzinfo=timezone.utc)

BASELINE_END = ROLLOUT_BASE_DATE + timedelta(days=2)       # Days 1-2: 100% v2.4.0
CANARY_END = ROLLOUT_BASE_DATE + timedelta(days=3)         # Day 3:    10% v2.4.1
ROLLOUT_END = ROLLOUT_BASE_DATE + timedelta(days=5)        # Days 4-5: 50% v2.4.1
FULL_ROLLOUT_END = ROLLOUT_BASE_DATE + timedelta(days=7)   # Days 6-7: 100% v2.4.1

CANARY_PERCENT = 10   # % of cohort that gets new version during canary
ROLLOUT_PERCENT = 50  # % during progressive rollout

# ---------------------------------------------------------------------------
# Model versions
# ---------------------------------------------------------------------------
MODEL_VERSION_OLD = "v2.4.0"
MODEL_VERSION_NEW = "v2.4.1"

# ---------------------------------------------------------------------------
# Fraud scoring
# ---------------------------------------------------------------------------
FRAUD_SCORE_THRESHOLD = 60   # score >= this → decline
BASE_SCORE = 20              # starting score for every order

# v2.4.0 penalties
V240_VELOCITY_MULTIPLIER = 5
V240_AMOUNT_THRESHOLDS = [(500, 10), (1000, 20), (2000, 30)]  # (amount, penalty)
V240_COUNTRY_MISMATCH_PENALTY = 15

# v2.4.1 penalties (more aggressive — this is the root cause)
V241_VELOCITY_MULTIPLIER = 15   # 3× more sensitive to velocity
V241_AMOUNT_THRESHOLDS = [(500, 12), (1000, 25), (2000, 35)]
V241_COUNTRY_MISMATCH_PENALTY = 20
V241_INTERNATIONAL_PENALTY = 10  # new: extra penalty for non-US shipping

# ---------------------------------------------------------------------------
# Temporal connection
# ---------------------------------------------------------------------------
TEMPORAL_HOST = "localhost:7233"
TEMPORAL_NAMESPACE = "default"
TEMPORAL_TASK_QUEUE = "blackbox-fraud-check"

# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------
NUM_ORDERS = 10_000
RANDOM_SEED = 42

# ---------------------------------------------------------------------------
# DuckDB
# ---------------------------------------------------------------------------
DUCKDB_PATH = "blackbox_warehouse.duckdb"

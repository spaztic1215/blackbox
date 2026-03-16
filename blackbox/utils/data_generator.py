"""Synthetic order generator for Blackbox demo.

Generates realistic e-commerce orders spread across the 7-day
rollout window with controlled distributions for amount, country,
and user velocity so the fraud model differences are clearly
detectable by the AI agent.

Key design decisions:
- ~3,000 unique users for 10K orders (realistic repeat-buyer ratio)
- Three user segments: one-time, regular, power buyers
- Velocity (user_order_count_24h) tracked per calendar day
- Country and amount distributions tuned to produce:
    ~8% decline rate on v2.4.0 (baseline)
    ~16% decline rate on v2.4.1 (spike)
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import timedelta, timezone
from typing import Optional

from faker import Faker

from blackbox.config import (
    FULL_ROLLOUT_END,
    NUM_ORDERS,
    RANDOM_SEED,
    ROLLOUT_BASE_DATE,
)
from blackbox.models.data import Order

fake = Faker()


# ---------------------------------------------------------------------------
# Country distribution — 60% US, 40% international
# ---------------------------------------------------------------------------
COUNTRY_WEIGHTS = {
    "US": 0.60,
    "CA": 0.10,
    "GB": 0.08,
    "DE": 0.06,
    "FR": 0.05,
    "JP": 0.04,
    "AU": 0.03,
    "BR": 0.02,
    "IN": 0.02,
}
COUNTRIES = list(COUNTRY_WEIGHTS.keys())
WEIGHTS = list(COUNTRY_WEIGHTS.values())

# ---------------------------------------------------------------------------
# User segments — controls repeat-buyer distribution
# ---------------------------------------------------------------------------
# (segment_name, fraction_of_users, orders_per_week_range)
USER_SEGMENTS = [
    ("one_time",  0.60, (1, 1)),    # 60% of users: single order
    ("occasional", 0.25, (2, 4)),   # 25%: 2-4 orders across the week
    ("regular",    0.10, (5, 12)),   # 10%: 5-12 orders (1-2/day)
    ("power",      0.05, (13, 35)),  # 5%:  13-35 orders (2-5/day)
]


def generate_orders(n: int = NUM_ORDERS, seed: int = RANDOM_SEED) -> list[Order]:
    """Generate n synthetic orders spread across the rollout window.

    Returns a list sorted by timestamp (oldest first).
    """
    random.seed(seed)
    Faker.seed(seed)

    # -------------------------------------------------------------------
    # Step 1: Create user pool with segment assignments
    # -------------------------------------------------------------------
    # Target ~3000 users for 10K orders
    # Back-calculate user count from segment weights and order ranges
    users = _create_user_pool(n, seed)

    # -------------------------------------------------------------------
    # Step 2: Assign orders to users across the 7-day window
    # -------------------------------------------------------------------
    raw_orders = _assign_orders_to_users(users, n)

    # -------------------------------------------------------------------
    # Step 3: Calculate per-day velocity for each order
    # -------------------------------------------------------------------
    _compute_daily_velocity(raw_orders)

    # Sort by timestamp
    raw_orders.sort(key=lambda o: o.timestamp)

    return raw_orders


def _create_user_pool(
    target_orders: int, seed: int
) -> list[dict]:
    """Build a user pool sized to produce ~target_orders total orders."""
    random.seed(seed)
    Faker.seed(seed)

    # Estimate how many users we need
    # Average orders per user ≈ weighted avg of segment midpoints
    avg_orders = sum(
        frac * (lo + hi) / 2
        for _, frac, (lo, hi) in USER_SEGMENTS
    )
    estimated_users = int(target_orders / avg_orders * 1.05)  # slight overestimate

    users = []
    for _ in range(estimated_users):
        user_id = f"user-{fake.uuid4()[:8]}"

        # Assign segment
        r = random.random()
        cumulative = 0.0
        segment = USER_SEGMENTS[0]
        for seg in USER_SEGMENTS:
            cumulative += seg[1]
            if r < cumulative:
                segment = seg
                break

        seg_name, _, (lo, hi) = segment
        order_count = random.randint(lo, hi)

        # Each user has a preferred country (sticky)
        country = random.choices(COUNTRIES, weights=WEIGHTS, k=1)[0]

        users.append({
            "user_id": user_id,
            "email": fake.email(),
            "ip_address": fake.ipv4(),
            "segment": seg_name,
            "order_count": order_count,
            "preferred_country": country,
        })

    return users


def _assign_orders_to_users(
    users: list[dict], target_orders: int
) -> list[Order]:
    """Distribute orders from users into the 7-day window."""
    window_seconds = int((FULL_ROLLOUT_END - ROLLOUT_BASE_DATE).total_seconds())
    orders: list[Order] = []
    order_idx = 0

    for user in users:
        if order_idx >= target_orders:
            break

        for _ in range(user["order_count"]):
            if order_idx >= target_orders:
                break

            # Random timestamp within the window
            offset = random.randint(0, window_seconds)
            ts = ROLLOUT_BASE_DATE + timedelta(seconds=offset)

            # Amount with realistic long-tail
            amount = _random_amount()

            # Shipping country — users mostly ship to their preferred country
            if random.random() < 0.85:
                shipping_country = user["preferred_country"]
            else:
                shipping_country = random.choices(COUNTRIES, weights=WEIGHTS, k=1)[0]

            # Billing/shipping mismatch — ~12% of orders
            if random.random() < 0.12:
                billing_country = random.choices(COUNTRIES, weights=WEIGHTS, k=1)[0]
            else:
                billing_country = shipping_country

            order = Order(
                order_id=f"order-{order_idx:05d}",
                user_id=user["user_id"],
                amount=round(amount, 2),
                shipping_country=shipping_country,
                billing_country=billing_country,
                timestamp=ts.isoformat(),
                email=user["email"],
                ip_address=user["ip_address"],
                user_order_count_24h=0,  # filled in by _compute_daily_velocity
            )
            orders.append(order)
            order_idx += 1

    return orders


def _compute_daily_velocity(orders: list[Order]) -> None:
    """Set user_order_count_24h based on actual per-calendar-day counts.

    For each order, velocity = how many orders that user has placed on
    the same calendar day (UTC), *including* this one.
    This is realistic — a fraud API would see the user's recent activity.
    """
    # Group by (user_id, calendar_date)
    daily_counts: dict[tuple[str, str], int] = defaultdict(int)
    order_days: list[tuple[str, str]] = []

    for order in orders:
        day_key = order.timestamp[:10]  # "2025-01-14" from ISO string
        key = (order.user_id, day_key)
        daily_counts[key] += 1
        order_days.append(key)

    # Assign velocity = total orders for that user on that day
    for i, order in enumerate(orders):
        key = order_days[i]
        # Use the total count for the day (simulates the fraud API seeing
        # all prior orders when evaluating this one)
        order.user_order_count_24h = daily_counts[key]


def _random_amount() -> float:
    """Generate order amounts with a realistic long-tail distribution.

    Calibrated to produce:
    - ~60% under $200 (low risk from amount alone)
    - ~25% $200-$500 (moderate)
    - ~12% $500-$1000 (triggers amount penalty)
    - ~3% $1000+ (triggers higher amount penalty)
    """
    r = random.random()
    if r < 0.35:
        return random.uniform(15, 80)       # 35%: small orders
    elif r < 0.60:
        return random.uniform(80, 200)      # 25%: medium-small
    elif r < 0.80:
        return random.uniform(200, 500)     # 20%: medium
    elif r < 0.92:
        return random.uniform(500, 1000)    # 12%: large (amount penalty kicks in)
    elif r < 0.97:
        return random.uniform(1000, 2000)   # 5%: high-value
    else:
        return random.uniform(2000, 5000)   # 3%: very high-value

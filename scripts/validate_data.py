"""Validate synthetic data quality without running Temporal.

Usage:
    python scripts/validate_data.py [--count 10000]

Shows:
- Order distributions (amounts, countries, velocity)
- Simulated decline rates per model version per rollout phase
- Flip cases: orders that approve on v2.4.0 but decline on v2.4.1
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone

from blackbox.config import (
    BASELINE_END,
    CANARY_END,
    ROLLOUT_BASE_DATE,
    ROLLOUT_END,
)
from blackbox.fraud_api.scorer import score_order
from blackbox.models.data import FraudResult
from blackbox.utils.data_generator import generate_orders
from blackbox.workflows.order_fraud import _assign_version, _user_cohort


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate generated data")
    parser.add_argument("--count", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"Generating {args.count} orders (seed={args.seed})...\n")
    orders = generate_orders(n=args.count, seed=args.seed)

    # ------------------------------------------------------------------
    # Basic distributions
    # ------------------------------------------------------------------
    print(f"{'='*60}")
    print(f"ORDER DISTRIBUTIONS ({len(orders)} orders)")
    print(f"{'='*60}")

    # Unique users
    user_ids = set(o.user_id for o in orders)
    print(f"\nUnique users: {len(user_ids)}")
    print(f"Avg orders/user: {len(orders)/len(user_ids):.1f}")

    # Amount distribution
    amt_buckets = {"< $100": 0, "$100-500": 0, "$500-1K": 0, "$1K-2K": 0, "$2K+": 0}
    for o in orders:
        if o.amount < 100: amt_buckets["< $100"] += 1
        elif o.amount < 500: amt_buckets["$100-500"] += 1
        elif o.amount < 1000: amt_buckets["$500-1K"] += 1
        elif o.amount < 2000: amt_buckets["$1K-2K"] += 1
        else: amt_buckets["$2K+"] += 1

    print(f"\nAmount distribution:")
    for label, count in amt_buckets.items():
        pct = count / len(orders) * 100
        bar = "█" * int(pct / 2)
        print(f"  {label:>10}: {count:>5} ({pct:5.1f}%) {bar}")

    # Country distribution
    country_counts: dict[str, int] = defaultdict(int)
    for o in orders:
        country_counts[o.shipping_country] += 1

    print(f"\nCountry distribution:")
    for country, count in sorted(country_counts.items(), key=lambda x: -x[1]):
        pct = count / len(orders) * 100
        print(f"  {country:>4}: {count:>5} ({pct:5.1f}%)")

    # Velocity distribution
    vel_buckets = defaultdict(int)
    for o in orders:
        vel_buckets[min(o.user_order_count_24h, 6)] += 1

    print(f"\nVelocity (orders/day) distribution:")
    for vel in sorted(vel_buckets.keys()):
        count = vel_buckets[vel]
        pct = count / len(orders) * 100
        label = f"{vel}+" if vel == 6 else str(vel)
        bar = "█" * int(pct / 2)
        print(f"  {label:>3}/day: {count:>5} ({pct:5.1f}%) {bar}")

    # Country mismatch rate
    mismatches = sum(1 for o in orders if o.billing_country != o.shipping_country)
    print(f"\nBilling/shipping mismatch: {mismatches} ({mismatches/len(orders)*100:.1f}%)")

    # ------------------------------------------------------------------
    # Simulate scoring with both models
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"SIMULATED FRAUD SCORING")
    print(f"{'='*60}")

    # Score every order with both models
    results_v240 = [score_order(o, "v2.4.0") for o in orders]
    results_v241 = [score_order(o, "v2.4.1") for o in orders]

    decline_240 = sum(1 for r in results_v240 if r.decision == "decline")
    decline_241 = sum(1 for r in results_v241 if r.decision == "decline")

    print(f"\nOverall decline rates (scoring all {len(orders)} orders):")
    print(f"  v2.4.0: {decline_240:>5} declines ({decline_240/len(orders)*100:.1f}%)")
    print(f"  v2.4.1: {decline_241:>5} declines ({decline_241/len(orders)*100:.1f}%)")

    # Flip cases
    flips = sum(
        1 for r240, r241 in zip(results_v240, results_v241)
        if r240.decision == "approve" and r241.decision == "decline"
    )
    print(f"  Flips (approve→decline): {flips} ({flips/len(orders)*100:.1f}%)")

    # ------------------------------------------------------------------
    # Decline rates by rollout phase (simulating actual version assignment)
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"DECLINE RATES BY ROLLOUT PHASE (with actual version assignment)")
    print(f"{'='*60}")

    phases = [
        ("Baseline (days 1-2)", ROLLOUT_BASE_DATE, BASELINE_END),
        ("Canary (day 3, 10%)", BASELINE_END, CANARY_END),
        ("Rollout (days 4-5, 50%)", CANARY_END, ROLLOUT_END),
        ("Full (days 6-7, 100%)", ROLLOUT_END, ROLLOUT_BASE_DATE.replace(year=2026)),
    ]

    for phase_name, phase_start, phase_end in phases:
        phase_orders = [
            o for o in orders
            if phase_start <= datetime.fromisoformat(o.timestamp) < phase_end
        ]
        if not phase_orders:
            continue

        # Assign actual version and score
        v240_count = 0
        v241_count = 0
        decline_on_v240 = 0
        decline_on_v241 = 0
        total_declines = 0

        for o in phase_orders:
            cohort = _user_cohort(o.user_id)
            version = _assign_version(o.timestamp, cohort)
            result = score_order(o, version)

            if version == "v2.4.0":
                v240_count += 1
                if result.decision == "decline":
                    decline_on_v240 += 1
                    total_declines += 1
            else:
                v241_count += 1
                if result.decision == "decline":
                    decline_on_v241 += 1
                    total_declines += 1

        overall_rate = total_declines / len(phase_orders) * 100 if phase_orders else 0
        v240_rate = decline_on_v240 / v240_count * 100 if v240_count else 0
        v241_rate = decline_on_v241 / v241_count * 100 if v241_count else 0

        print(f"\n  {phase_name}:")
        print(f"    Orders: {len(phase_orders)}")
        print(f"    v2.4.0: {v240_count:>5} orders, {decline_on_v240:>4} declines ({v240_rate:.1f}%)")
        print(f"    v2.4.1: {v241_count:>5} orders, {decline_on_v241:>4} declines ({v241_rate:.1f}%)")
        print(f"    Overall decline rate: {overall_rate:.1f}%")

    # ------------------------------------------------------------------
    # Sample flip cases for inspection
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"SAMPLE FLIP CASES (approve on v2.4.0, decline on v2.4.1)")
    print(f"{'='*60}\n")

    shown = 0
    for o, r240, r241 in zip(orders, results_v240, results_v241):
        if r240.decision == "approve" and r241.decision == "decline" and shown < 5:
            print(f"  {o.order_id}: user={o.user_id[:12]}, amount=${o.amount:.0f}, "
                  f"country={o.shipping_country}, velocity={o.user_order_count_24h}/day")
            print(f"    v2.4.0: score={r240.score:>3} → {r240.decision:>7}  factors={r240.raw_factors}")
            print(f"    v2.4.1: score={r241.score:>3} → {r241.decision:>7}  factors={r241.raw_factors}")
            print()
            shown += 1


if __name__ == "__main__":
    main()

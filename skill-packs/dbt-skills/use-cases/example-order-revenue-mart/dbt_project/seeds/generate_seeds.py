#!/usr/bin/env python3
"""Generate the raw seed CSVs for the worked example.

Seeds stand in for the Fivetran-landed raw tables. They are committed, so the project
runs without this script — but the load timestamps go stale, and `dbt source freshness`
will report a breach. Re-run this to anchor them to now:

    python3 seeds/generate_seeds.py

Deterministic: a fixed RNG seed, so two runs on the same day produce identical files and
the git diff is only the timestamps.

The data deliberately contains the awkward cases the models claim to handle:
  - ~3% guest checkouts        -> null customer_id, the nullable-FK / unknown-member case
  - ~0.3% orders with no lines -> the coalesce-to-zero case
  - test orders                -> filtered in intermediate, not in staging
  - soft-deleted rows          -> filtered in staging via _fivetran_deleted
  - one unmapped country       -> exercises the 'OTHER' region branch
  - an unknown payment status  -> exercises the CASE fall-through to 'unknown'

And for the second connector, Demo POS (the worked connector-onboarding example):
  - ~25% walk-in receipts      -> no customer_ref, the nullable-FK case again
  - shouting statuses ('PAID') -> lowercased and trimmed in staging
  - one padded status/country  -> proves the trim() actually runs
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
RNG = random.Random(20260728)

NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0, tzinfo=None)
N_CUSTOMERS = 120
N_ORDERS = 500
N_POS_CUSTOMERS = 40
N_RECEIPTS = 200

COUNTRIES = ["us", "ca", "gb", "fr", "de", "es", "mx", "nl", "se", "it"]
PAYMENT_STATUSES = ["paid"] * 60 + ["pending"] * 15 + ["fulfilled"] * 10 + \
                   ["refunded"] * 10 + ["cancelled"] * 5


def iso(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def write(name: str, header: list, rows: list) -> None:
    path = os.path.join(HERE, name)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  {name}: {len(rows)} rows")


def main() -> None:
    # ---------------------------------------------------------------- customers
    customers = []
    for i in range(1, N_CUSTOMERS + 1):
        customer_id = f"c_{i:04d}"
        country = COUNTRIES[i % len(COUNTRIES)]
        if i == N_CUSTOMERS:
            country = "jp"          # unmapped -> region 'OTHER'
        created = NOW - dt.timedelta(days=RNG.randint(30, 900))
        customers.append([
            customer_id,
            f"customer{i:04d}@example.com",
            country.upper() if i % 7 == 0 else country,   # mixed case; staging lowers it
            iso(created),
            iso(NOW - dt.timedelta(minutes=RNG.randint(5, 90))),
            "false",
        ])
    # one soft-deleted customer, to prove staging filters it
    customers.append([
        "c_9999", "deleted@example.com", "us", iso(NOW - dt.timedelta(days=400)),
        iso(NOW - dt.timedelta(minutes=20)), "true",
    ])
    write("raw_customers.csv",
          ["id", "email", "country_code", "created_at", "_fivetran_synced",
           "_fivetran_deleted"],
          customers)

    # ------------------------------------------------------------------- orders
    orders, order_ids_without_lines, line_rows = [], set(), []
    for i in range(1, N_ORDERS + 1):
        order_id = f"o_{i:05d}"

        # ~3% guest checkouts: no customer_id at all
        customer_id = "" if i % 33 == 0 else f"c_{RNG.randint(1, N_CUSTOMERS):04d}"

        status = RNG.choice(PAYMENT_STATUSES)
        if i == 7:
            status = "partially_refunded"     # unknown enum -> CASE fall-through
        if i == 11:
            status = ""                       # null -> 'unknown'

        is_test = "true" if i % 97 == 0 else "false"
        soft_deleted = "true" if i % 149 == 0 else "false"

        ordered_at = NOW - dt.timedelta(hours=RNG.randint(1, 24 * 45))
        synced_at = ordered_at + dt.timedelta(minutes=RNG.randint(5, 120))
        if synced_at > NOW:
            synced_at = NOW - dt.timedelta(minutes=5)

        # ~0.3% of orders have no line items (real upstream defect)
        has_lines = i % 300 != 0
        if not has_lines:
            order_ids_without_lines.add(order_id)

        total = 0.0
        if has_lines:
            for line_no in range(1, RNG.randint(1, 4) + 1):
                price = round(RNG.uniform(9.99, 499.99), 2)
                discount = round(price * RNG.choice([0, 0, 0, 0.1, 0.25]), 2)
                total += price - discount
                line_rows.append([
                    f"{order_id}_l{line_no}", order_id, f"p_{RNG.randint(1, 60):03d}",
                    RNG.randint(1, 3), f"{price:.2f}", f"{discount:.2f}",
                    iso(synced_at),
                    # A soft-deleted order's lines are soft-deleted too. Emitting live
                    # lines for a deleted order would orphan them the moment staging
                    # filters `_fivetran_deleted`, and the relationships test would fail
                    # — correctly. The connector deletes the whole tree.
                    soft_deleted,
                ])

        orders.append([
            order_id, customer_id, status, "USD", f"{total + 12.50:.2f}",
            is_test, iso(ordered_at), iso(synced_at), soft_deleted,
        ])

    write("raw_orders.csv",
          ["id", "customer_id", "financial_status", "currency", "total_price", "test",
           "created_at", "_fivetran_synced", "_fivetran_deleted"],
          orders)
    write("raw_order_lines.csv",
          ["id", "order_id", "product_id", "quantity", "price", "discount",
           "_fivetran_synced", "_fivetran_deleted"],
          line_rows)

    # ----------------------------------------------------------------- demopos
    # The second connector: a synthetic in-store till, the worked example of onboarding
    # a connector. One nightly full export, every row stamped with the same exported_at
    # — which is exactly what the freshness block in _demopos__sources.yml describes.
    pos_exported_at = NOW - dt.timedelta(hours=3)

    pos_customers = []
    for i in range(1, N_POS_CUSTOMERS + 1):
        country = COUNTRIES[(i * 3) % len(COUNTRIES)]
        if i % 5 == 0:
            country = country.upper()       # staging lowercases it
        if i == 3:
            country = f" {country} "        # staging trims it
        pos_customers.append([
            f"pc_{i:04d}",
            f"till{i:04d}@example.com",
            country,
            iso(NOW - dt.timedelta(days=RNG.randint(10, 700))),
            iso(pos_exported_at),
        ])
    write("raw_demopos_customers.csv",
          ["customer_ref", "email_address", "country", "signed_up_at", "exported_at"],
          pos_customers)

    receipts, walk_ins = [], 0
    for i in range(1, N_RECEIPTS + 1):
        # ~25% walk-in cash sales: nobody scanned a loyalty card, so no customer_ref
        if i % 4 == 0:
            customer_ref = ""
            walk_ins += 1
        else:
            customer_ref = f"pc_{RNG.randint(1, N_POS_CUSTOMERS):04d}"
        status = RNG.choice(["PAID"] * 85 + ["REFUNDED"] * 10 + ["VOID"] * 5)
        if i == 5:
            status = " Paid "               # staging lowercases and trims
        receipts.append([
            f"r_{i:05d}",
            customer_ref,
            status,
            "USD",
            f"{RNG.uniform(3.50, 250.00):.2f}",
            iso(NOW - dt.timedelta(hours=RNG.randint(1, 24 * 45))),
            f"reg_{RNG.randint(1, 3):02d}",
            iso(pos_exported_at),
        ])
    write("raw_demopos_receipts.csv",
          ["receipt_ref", "customer_ref", "status", "currency", "total_amount",
           "sold_at", "register_id", "exported_at"],
          receipts)

    print(f"\n  {len(order_ids_without_lines)} order(s) with no line items — "
          f"the coalesce-to-zero case")
    print(f"  {sum(1 for o in orders if not o[1])} guest checkout(s) — the nullable-FK case")
    print(f"  {walk_ins} walk-in receipt(s) with no customer — the same case, at the till")
    print(f"  seeds anchored to {iso(NOW)} UTC")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build synthetic dbt artifacts for the worked example.

The scaffold's scripts read dbt's JSON artifacts. To make them runnable without a
warehouse — or a dbt install — this generates a small but realistic
manifest.json / run_results.json / sources.json / catalog.json, plus a "production"
manifest that differs from the current one so the breaking-change detector has
something to find.

The synthetic project deliberately contains real defects: an untested mart, an
undocumented model, a hardcoded table reference, an incremental model with no
unique_key, a source with no freshness block, and a stale source. Every script should
find them.

    python use-cases/example-order-revenue-mart/artifacts/build_artifacts.py
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = "analytics"


def model(name, path, layer, raw, depends=(), columns=None, config=None,
          description="", access=None, contract=False, latest_version=None):
    cfg = {"materialized": "view" if layer == "staging" else "table",
           "tags": [layer], "enabled": True}
    cfg.update(config or {})
    if access:
        cfg["access"] = access
    if contract:
        cfg["contract"] = {"enforced": True}
    return {
        "unique_id": f"model.{PROJECT}.{name}",
        "name": name,
        "resource_type": "model",
        "package_name": PROJECT,
        "path": path,
        "original_file_path": f"models/{path}",
        "database": "ANALYTICS",
        "schema": layer,
        "alias": name,
        "description": description,
        "raw_code": raw,
        "columns": columns or {},
        "config": cfg,
        "depends_on": {"nodes": list(depends), "macros": []},
        "tags": [layer],
        **({"latest_version": latest_version} if latest_version else {}),
    }


def column(desc="", dtype=""):
    return {"description": desc, "data_type": dtype, "meta": {}, "tags": []}


def test(name, model_uid, test_name, col=None, kwargs=None):
    uid = f"test.{PROJECT}.{name}"
    return uid, {
        "unique_id": uid,
        "name": name,
        "resource_type": "test",
        "package_name": PROJECT,
        "path": f"{name}.sql",
        "original_file_path": f"models/marts/_schema.yml",
        "column_name": col,
        "attached_node": model_uid,
        "test_metadata": {"name": test_name, "kwargs": kwargs or {}},
        "depends_on": {"nodes": [model_uid], "macros": []},
        "config": {"severity": "ERROR", "enabled": True},
        "columns": {},
        "description": "",
    }


def unit_test(name, model_name, model_uid):
    uid = f"unit_test.{PROJECT}.{model_name}.{name}"
    return uid, {
        "unique_id": uid,
        "name": name,
        "resource_type": "unit_test",
        "package_name": PROJECT,
        "model": model_name,
        "path": "_unit_tests.yml",
        "original_file_path": "models/intermediate/finance/_unit_tests.yml",
        "depends_on": {"nodes": [model_uid], "macros": []},
        "config": {"enabled": True},
        "columns": {},
        "description": "",
    }


def source(source_name, table, freshness=None, loaded_at=None, columns=None):
    uid = f"source.{PROJECT}.{source_name}.{table}"
    node = {
        "unique_id": uid,
        "name": table,
        "source_name": source_name,
        "resource_type": "source",
        "package_name": PROJECT,
        "database": "RAW",
        "schema": source_name,
        "identifier": table,
        "path": f"models/staging/{source_name}/_{source_name}__sources.yml",
        "original_file_path": f"models/staging/{source_name}/_{source_name}__sources.yml",
        "loaded_at_field": loaded_at,
        "freshness": freshness,
        "columns": columns or {},
        "description": "",
        "config": {"enabled": True},
        "unrendered_config": {"freshness": freshness} if freshness else {},
        "depends_on": {"nodes": [], "macros": []},
    }
    return uid, node


def freshness(warn_h, error_h):
    return {
        "warn_after": {"count": warn_h, "period": "hour"},
        "error_after": {"count": error_h, "period": "hour"},
        "filter": None,
    }


# ---------------------------------------------------------------- the project

nodes = {}
sources = {}
exposures = {}

# --- sources
for uid, node in [
    source("shopify", "orders", freshness(1, 6), "_fivetran_synced",
           {"id": column("Shopify order id", "varchar")}),
    source("shopify", "order_lines", freshness(1, 6), "_fivetran_synced"),
    source("shopify", "customers", freshness(12, 24), "_fivetran_synced"),
    # Deliberate defect: no freshness block at all — an undocumented SLA.
    source("netsuite", "revenue_postings", None, None),
]:
    sources[uid] = node

S = lambda s, t: f"source.{PROJECT}.{s}.{t}"
M = lambda n: f"model.{PROJECT}.{n}"

# --- staging
nodes[M("stg_shopify__orders")] = model(
    "stg_shopify__orders", "staging/shopify/stg_shopify__orders.sql", "staging",
    raw="""with source as (
    select * from {{ source('shopify', 'orders') }}
),
renamed as (
    select
        id                            as order_id,
        customer_id,
        lower(trim(financial_status)) as payment_status,
        cast(total_price as numeric)  as order_amount,
        coalesce(test, false)         as is_test_order,
        cast(created_at as timestamp) as ordered_at,
        _fivetran_synced              as _loaded_at
    from source
    where not coalesce(_fivetran_deleted, false)
)
select * from renamed""",
    depends=[S("shopify", "orders")],
    description="One row per Shopify order, renamed and cast. Soft deletes excluded.",
    columns={
        "order_id": column("Primary key. Shopify order id.", "varchar"),
        "customer_id": column("FK to customers. Null for guest checkouts.", "varchar"),
        "payment_status": column("Lowercased financial_status.", "varchar"),
        "order_amount": column("Gross order amount, source currency.", "numeric(28,6)"),
        "is_test_order": column("True for Shopify test orders.", "boolean"),
        "ordered_at": column("Order creation timestamp, UTC.", "timestamp"),
        "_loaded_at": column("Fivetran sync timestamp.", "timestamp"),
    },
)

nodes[M("stg_shopify__order_lines")] = model(
    "stg_shopify__order_lines", "staging/shopify/stg_shopify__order_lines.sql", "staging",
    raw="""with source as (
    select * from {{ source('shopify', 'order_lines') }}
)
select
    id                  as order_line_id,
    order_id,
    product_id,
    quantity,
    cast(price as numeric) as line_amount,
    cast(discount as numeric) as discount_amount
from source""",
    depends=[S("shopify", "order_lines")],
    description="One row per order line item.",
    columns={
        "order_line_id": column("Primary key.", "varchar"),
        "order_id": column("FK to stg_shopify__orders.", "varchar"),
        "product_id": column("FK to products.", "varchar"),
        "quantity": column("Units ordered.", "integer"),
        "line_amount": column("Line total before discount.", "numeric(28,6)"),
        "discount_amount": column("Discount applied to this line.", "numeric(28,6)"),
    },
)

# Deliberate defect: no description at all.
nodes[M("stg_shopify__customers")] = model(
    "stg_shopify__customers", "staging/shopify/stg_shopify__customers.sql", "staging",
    raw="""select
    id           as customer_id,
    email        as customer_email,
    lower(country_code) as country_code,
    cast(created_at as timestamp) as first_seen_at
from {{ source('shopify', 'customers') }}""",
    depends=[S("shopify", "customers")],
    columns={
        "customer_id": column("", "varchar"),
        "customer_email": column("", "varchar"),
        "country_code": column("", "varchar"),
        "first_seen_at": column("", "timestamp"),
    },
)

# Deliberate defect: hardcoded table reference instead of source().
nodes[M("stg_netsuite__revenue_postings")] = model(
    "stg_netsuite__revenue_postings",
    "staging/netsuite/stg_netsuite__revenue_postings.sql", "staging",
    raw="""select
    posting_id,
    cast(posting_date as date) as posting_date,
    cast(amount as numeric)    as amount_usd
from raw.netsuite.revenue_postings""",
    depends=[],
    description="Finance ledger revenue postings, used for reconciliation.",
    columns={
        "posting_id": column("Primary key.", "varchar"),
        "posting_date": column("Ledger posting date.", "date"),
        "amount_usd": column("Posted amount, USD.", "numeric(28,6)"),
    },
)

# --- intermediate
nodes[M("int_orders_with_line_totals")] = model(
    "int_orders_with_line_totals",
    "intermediate/finance/int_orders_with_line_totals.sql", "intermediate",
    raw="""with orders as (
    select * from {{ ref('stg_shopify__orders') }}
),
line_items as (
    select * from {{ ref('stg_shopify__order_lines') }}
),
line_totals as (
    select
        order_id,
        count(*)             as line_item_count,
        sum(line_amount)     as gross_line_amount,
        sum(discount_amount) as discount_amount
    from line_items
    group by 1
),
final as (
    select
        orders.order_id,
        orders.customer_id,
        orders.ordered_at,
        orders.order_amount,
        case
            when orders.payment_status = 'refunded' then 'refunded'
            when orders.payment_status = 'paid'     then 'paid'
            when orders.payment_status is null      then 'unknown'
            else orders.payment_status
        end as order_status,
        coalesce(line_totals.line_item_count, 0)   as line_item_count,
        coalesce(line_totals.gross_line_amount, 0) as gross_line_amount,
        coalesce(line_totals.discount_amount, 0)   as discount_amount
    from orders
    left join line_totals on orders.order_id = line_totals.order_id
    where not orders.is_test_order
)
select * from final""",
    depends=[M("stg_shopify__orders"), M("stg_shopify__order_lines")],
    config={"materialized": "ephemeral"},
    description="One row per non-test order, with line-item totals collapsed to the "
                "order grain before joining. Resolves the line-item fan-out.",
    columns={
        "order_id": column("Primary key.", "varchar"),
        "customer_id": column("FK to dim_customers.", "varchar"),
        "ordered_at": column("Order timestamp, UTC.", "timestamp"),
        "order_amount": column("Gross order amount.", "numeric(28,6)"),
        "order_status": column("Business status; refund overrides fulfillment.", "varchar"),
        "line_item_count": column("Number of line items.", "integer"),
        "gross_line_amount": column("Sum of line amounts.", "numeric(28,6)"),
        "discount_amount": column("Sum of line discounts.", "numeric(28,6)"),
    },
)

# --- marts
nodes[M("dim_customers")] = model(
    "dim_customers", "marts/finance/dim_customers.sql", "marts",
    raw="""with customers as (
    select * from {{ ref('stg_shopify__customers') }}
),
final as (
    select
        customer_id,
        customer_email,
        country_code,
        case when country_code in ('gb','fr','de','es','it') then 'EMEA'
             when country_code in ('us','ca','mx') then 'AMER'
             else 'OTHER' end as region,
        first_seen_at
    from customers
)
select * from final""",
    depends=[M("stg_shopify__customers")],
    description="One row per customer, current state. Region derived from country_code.",
    columns={
        "customer_id": column("Primary key.", "varchar"),
        "customer_email": column("Contact email. PII — masked in non-prod.", "varchar"),
        "country_code": column("ISO-2 country code, lowercased.", "varchar"),
        "region": column("EMEA | AMER | OTHER, derived from country_code.", "varchar"),
        "first_seen_at": column("First seen timestamp.", "timestamp"),
    },
)

nodes[M("fct_orders")] = model(
    "fct_orders", "marts/finance/fct_orders.sql", "marts",
    raw="""with orders as (
    select * from {{ ref('int_orders_with_line_totals') }}
    {% if is_incremental() %}
    where ordered_at >= (select dateadd(day, -3, max(ordered_at)) from {{ this }})
    {% endif %}
),
customers as (
    select * from {{ ref('dim_customers') }}
),
final as (
    select
        orders.order_id,
        orders.customer_id,
        customers.region,
        orders.order_status,
        orders.line_item_count,
        orders.order_amount                                as order_amount_usd,
        orders.gross_line_amount - orders.discount_amount  as net_line_amount_usd,
        orders.ordered_at,
        cast(orders.ordered_at as date)                    as ordered_date
    from orders
    left join customers on orders.customer_id = customers.customer_id
)
select * from final""",
    depends=[M("int_orders_with_line_totals"), M("dim_customers")],
    config={"materialized": "incremental", "incremental_strategy": "merge",
            "unique_key": "order_id", "on_schema_change": "append_new_columns",
            "cluster_by": ["ordered_date"]},
    contract=True,
    access="public",
    description="One row per order at its current status. Excludes internal test "
                "accounts. Amounts are USD at the order-date rate.",
    columns={
        "order_id": column("Primary key. Shopify order id.", "varchar"),
        "customer_id": column("FK to dim_customers. Null for guest checkouts.", "varchar"),
        "region": column("Customer region at time of query.", "varchar"),
        "order_status": column("pending|paid|fulfilled|refunded|cancelled", "varchar"),
        "line_item_count": column("Number of line items.", "integer"),
        "order_amount_usd": column("Gross order amount, USD.", "numeric(28,6)"),
        "net_line_amount_usd": column("Line totals less discounts, USD.", "numeric(28,6)"),
        "ordered_at": column("Order timestamp, UTC.", "timestamp"),
        "ordered_date": column("Order date, UTC.", "date"),
    },
)

# Deliberate defects: no tests, no description, select * in the mart, no consumer,
# incremental with no unique_key, on_schema_change left at the default.
nodes[M("fct_order_line_detail")] = model(
    "fct_order_line_detail", "marts/finance/fct_order_line_detail.sql", "marts",
    raw="""with lines as (
    select * from {{ ref('stg_shopify__order_lines') }}
)
select * from lines""",
    depends=[M("stg_shopify__order_lines")],
    config={"materialized": "incremental", "incremental_strategy": "merge"},
)

nodes[M("metricflow_time_spine")] = model(
    "metricflow_time_spine", "marts/metricflow_time_spine.sql", "marts",
    raw="{{ dbt_utils.date_spine(datepart='day', "
        "start_date=\"cast('2019-01-01' as date)\", "
        "end_date=\"dateadd(year, 2, current_date)\") }}",
    depends=[],
    description="Daily calendar spine for MetricFlow cumulative metrics and offsets.",
    columns={"date_day": column("Calendar date, one row per day.", "date")},
)

# --- tests
for uid, node in [
    test("unique_stg_shopify__orders_order_id", M("stg_shopify__orders"), "unique", "order_id"),
    test("not_null_stg_shopify__orders_order_id", M("stg_shopify__orders"), "not_null", "order_id"),
    test("unique_stg_shopify__order_lines_order_line_id", M("stg_shopify__order_lines"), "unique", "order_line_id"),
    test("not_null_stg_shopify__order_lines_order_line_id", M("stg_shopify__order_lines"), "not_null", "order_line_id"),
    test("unique_stg_shopify__customers_customer_id", M("stg_shopify__customers"), "unique", "customer_id"),
    test("not_null_stg_shopify__customers_customer_id", M("stg_shopify__customers"), "not_null", "customer_id"),
    test("unique_dim_customers_customer_id", M("dim_customers"), "unique", "customer_id"),
    test("not_null_dim_customers_customer_id", M("dim_customers"), "not_null", "customer_id"),
    test("accepted_values_dim_customers_region", M("dim_customers"), "accepted_values",
         "region", {"values": ["EMEA", "AMER", "OTHER"]}),
    test("unique_fct_orders_order_id", M("fct_orders"), "unique", "order_id"),
    test("not_null_fct_orders_order_id", M("fct_orders"), "not_null", "order_id"),
    test("relationships_fct_orders_customer_id", M("fct_orders"), "relationships",
         "customer_id", {"to": "ref('dim_customers')", "field": "customer_id"}),
    test("accepted_values_fct_orders_order_status", M("fct_orders"), "accepted_values",
         "order_status", {"values": ["pending", "paid", "fulfilled", "refunded", "cancelled"]}),
    test("unique_int_orders_with_line_totals_order_id", M("int_orders_with_line_totals"),
         "unique", "order_id"),
    test("not_null_int_orders_with_line_totals_order_id", M("int_orders_with_line_totals"),
         "not_null", "order_id"),
    unit_test("test_refund_overrides_status", "int_orders_with_line_totals",
              M("int_orders_with_line_totals")),
    unit_test("test_unknown_status_falls_through", "int_orders_with_line_totals",
              M("int_orders_with_line_totals")),
]:
    nodes[uid] = node

# --- exposure
exposures["exposure." + PROJECT + ".executive_revenue_dashboard"] = {
    "unique_id": f"exposure.{PROJECT}.executive_revenue_dashboard",
    "name": "executive_revenue_dashboard",
    "resource_type": "exposure",
    "type": "dashboard",
    "maturity": "high",
    "url": "https://bi.example.com/dashboards/42",
    "owner": {"name": "Priya Raman", "email": "priya@example.com"},
    "description": "Board-level weekly revenue, read every Monday 08:00 UTC.",
    "depends_on": {"nodes": [M("fct_orders"), M("dim_customers")], "macros": []},
    "package_name": PROJECT,
    "path": "marts/finance/_finance__models.yml",
    "original_file_path": "models/marts/finance/_finance__models.yml",
    "config": {"enabled": True},
    "columns": {},
}


def build_maps(all_nodes):
    parent_map, child_map = {}, {uid: [] for uid in all_nodes}
    for uid, node in all_nodes.items():
        parents = list((node.get("depends_on") or {}).get("nodes", []) or [])
        parent_map[uid] = parents
        for parent in parents:
            child_map.setdefault(parent, []).append(uid)
    return parent_map, child_map


all_nodes = {**nodes, **sources, **exposures}
parent_map, child_map = build_maps(all_nodes)

manifest = {
    "metadata": {
        "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json",
        "dbt_version": "1.9.0",
        "generated_at": "2026-07-27T09:00:00.000000Z",
        "project_name": PROJECT,
        "adapter_type": "snowflake",
    },
    "nodes": nodes,
    "sources": sources,
    "exposures": exposures,
    "metrics": {},
    "semantic_models": {},
    "saved_queries": {},
    "macros": {},
    "docs": {},
    "selectors": {},
    "parent_map": parent_map,
    "child_map": child_map,
    "group_map": {},
    "disabled": {},
}

# ---------------------------------------------------------------- prod manifest
# Production is one release behind: fct_orders had a `currency_code` column, region
# was not yet present, order_amount_usd was plain `numeric`, and
# fct_order_line_detail did not exist. That gives the breaking-change detector real
# findings: a removed column and a data_type change on a contracted model.

prod_nodes = json.loads(json.dumps(nodes))
prod_fct = prod_nodes[M("fct_orders")]
prod_fct["columns"]["currency_code"] = column("ISO currency code.", "varchar")
del prod_fct["columns"]["region"]
prod_fct["columns"]["order_amount_usd"]["data_type"] = "numeric"
prod_fct["raw_code"] = prod_fct["raw_code"].replace("customers.region,\n        ", "")
del prod_nodes[M("fct_order_line_detail")]

prod_all = {**prod_nodes, **sources, **exposures}
prod_parent, prod_child = build_maps(prod_all)
prod_manifest = json.loads(json.dumps(manifest))
prod_manifest["nodes"] = prod_nodes
prod_manifest["parent_map"] = prod_parent
prod_manifest["child_map"] = prod_child
prod_manifest["metadata"]["generated_at"] = "2026-07-20T09:00:00.000000Z"

# ---------------------------------------------------------------- run results

timings = {
    M("stg_shopify__orders"): 4.2,
    M("stg_shopify__order_lines"): 6.8,
    M("stg_shopify__customers"): 2.1,
    M("stg_netsuite__revenue_postings"): 1.4,
    M("dim_customers"): 8.5,
    M("fct_orders"): 142.7,
    M("fct_order_line_detail"): 61.3,
    M("metricflow_time_spine"): 3.0,
}
test_timings = {
    uid: (28.4 if "relationships" in uid else 5.5 if "unique" in uid else 1.8)
    for uid in nodes
    if nodes[uid].get("resource_type") in ("test", "unit_test")
}
test_timings = {uid: (0.4 if nodes[uid]["resource_type"] == "unit_test" else t)
                for uid, t in test_timings.items()}

results = []
for uid, secs in {**timings, **test_timings}.items():
    failing = uid.endswith("accepted_values_fct_orders_order_status")
    results.append({
        "unique_id": uid,
        "status": "fail" if failing else "success" if uid.startswith("model.") else "pass",
        "execution_time": secs,
        "message": ("Got 3 results, configured to fail if != 0"
                    if failing else None),
        "failures": 3 if failing else (0 if not uid.startswith("model.") else None),
        "adapter_response": {"_message": "SUCCESS", "rows_affected": 12043}
        if uid.startswith("model.") else {},
        "timing": [{"name": "compile", "started_at": "2026-07-27T09:00:00Z",
                    "completed_at": "2026-07-27T09:00:01Z"},
                   {"name": "execute", "started_at": "2026-07-27T09:00:01Z",
                    "completed_at": "2026-07-27T09:00:02Z"}],
        "thread_id": "Thread-1",
    })

run_results = {
    "metadata": {"dbt_version": "1.9.0",
                 "generated_at": "2026-07-27T09:05:00.000000Z",
                 "invocation_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
    "results": results,
    "elapsed_time": 187.4,
    "args": {"which": "build", "target": "prod", "threads": 8, "select": []},
}

# A previous run, so --compare finds a real regression on fct_orders.
prev_results = json.loads(json.dumps(run_results))
for r in prev_results["results"]:
    if r["unique_id"] == M("fct_orders"):
        r["execution_time"] = 58.1
    elif r["unique_id"] == M("fct_order_line_detail"):
        r["execution_time"] = 59.8
    elif r["unique_id"].endswith("accepted_values_fct_orders_order_status"):
        r["status"] = "pass"
        r["failures"] = 0
        r["message"] = None
prev_results["elapsed_time"] = 104.9
prev_results["metadata"]["generated_at"] = "2026-07-26T09:05:00.000000Z"

# ---------------------------------------------------------------- sources.json

sources_json = {
    "metadata": {"dbt_version": "1.9.0",
                 "generated_at": "2026-07-27T09:00:00.000000Z"},
    "elapsed_time": 4.1,
    "results": [
        {"unique_id": S("shopify", "orders"), "status": "pass",
         "max_loaded_at": "2026-07-27T08:40:00+00:00",
         "snapshotted_at": "2026-07-27T09:00:00+00:00",
         "max_loaded_at_time_ago_in_s": 1200,
         "criteria": {"warn_after": {"count": 1, "period": "hour"},
                      "error_after": {"count": 6, "period": "hour"}}},
        {"unique_id": S("shopify", "order_lines"), "status": "warn",
         "max_loaded_at": "2026-07-27T05:00:00+00:00",
         "snapshotted_at": "2026-07-27T09:00:00+00:00",
         "max_loaded_at_time_ago_in_s": 14400,
         "criteria": {"warn_after": {"count": 1, "period": "hour"},
                      "error_after": {"count": 6, "period": "hour"}}},
        {"unique_id": S("shopify", "customers"), "status": "error",
         "max_loaded_at": "2026-07-25T18:00:00+00:00",
         "snapshotted_at": "2026-07-27T09:00:00+00:00",
         "max_loaded_at_time_ago_in_s": 140400,
         "criteria": {"warn_after": {"count": 12, "period": "hour"},
                      "error_after": {"count": 24, "period": "hour"}}},
    ],
}

# ---------------------------------------------------------------- catalog.json

catalog = {
    "metadata": {"dbt_version": "1.9.0",
                 "generated_at": "2026-07-27T09:10:00.000000Z"},
    "nodes": {}, "sources": {}, "errors": None,
}
for uid, node in nodes.items():
    if node.get("resource_type") != "model" or not node.get("columns"):
        continue
    catalog["nodes"][uid] = {
        "unique_id": uid,
        "metadata": {"type": "BASE TABLE", "schema": node["schema"],
                     "name": node["name"], "database": node["database"]},
        "columns": {
            col: {"type": (meta.get("data_type") or "VARCHAR").upper(),
                  "index": i + 1, "name": col, "comment": meta.get("description")}
            for i, (col, meta) in enumerate(node["columns"].items())
        },
        "stats": {}, "columns_hash": "",
    }
for uid, node in sources.items():
    catalog["sources"][uid] = {
        "unique_id": uid,
        "metadata": {"type": "BASE TABLE", "schema": node["schema"],
                     "name": node["name"], "database": node["database"]},
        "columns": {"id": {"type": "VARCHAR", "index": 1, "name": "id"}},
        "stats": {},
    }


def write(name, payload, subdir=""):
    path = os.path.join(HERE, subdir, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    print(f"  wrote {os.path.relpath(path, os.path.dirname(HERE))}")


if __name__ == "__main__":
    print("Building synthetic dbt artifacts for the worked example:")
    write("manifest.json", manifest, "target")
    write("run_results.json", run_results, "target")
    write("sources.json", sources_json, "target")
    write("catalog.json", catalog, "target")
    write("manifest.json", prod_manifest, "prod")
    write("run_results.json", prev_results, "prod")
    print("\nRun the scaffold's tools against them:")
    print("  python scripts/dbt_project_auditor.py "
          "--manifest use-cases/example-order-revenue-mart/artifacts/target/manifest.json")

# Imported from dbt

- dbt project: `analytics`
- dbt profile/target: `analytics.duckdb_dev`
- imported models: 8
- imported sources: 5
- imported relationships: 3

Structural metadata comes from `manifest.json` and `catalog.json`. The sections below summarize dbt test-derived constraints and warnings.

## Verified Constraints

- dim_customers.customer_id: NOT NULL, UNIQUE (primary key)
- dim_customers.region: accepted values = EMEA, AMER, OTHER
- fct_orders.order_amount_usd: NOT NULL
- fct_orders.order_id: NOT NULL, UNIQUE (primary key)
- fct_orders.order_status: NOT NULL
- fct_orders.order_status: accepted values = pending, paid, fulfilled, refunded, cancelled, unknown
- fct_orders.ordered_at: NOT NULL
- metricflow_time_spine.date_day: NOT NULL, UNIQUE (primary key)
- raw_customers.customer_ref: NOT NULL, UNIQUE (primary key)
- raw_order_lines.id: NOT NULL, UNIQUE (primary key)
- raw_orders.id: NOT NULL, UNIQUE (primary key)
- raw_receipts.receipt_ref: NOT NULL, UNIQUE (primary key)
- raw_shopify_customers.id: NOT NULL, UNIQUE (primary key)
- stg_demopos__customers.customer_id: NOT NULL, UNIQUE (primary key)
- stg_demopos__receipts.receipt_amount: NOT NULL
- stg_demopos__receipts.receipt_id: NOT NULL, UNIQUE (primary key)
- stg_demopos__receipts.receipt_status: accepted values = paid, refunded, void
- stg_demopos__receipts.sold_at: NOT NULL
- stg_shopify__customers.customer_id: NOT NULL, UNIQUE (primary key)
- stg_shopify__order_lines.order_id: NOT NULL
- stg_shopify__order_lines.order_line_id: NOT NULL, UNIQUE (primary key)
- stg_shopify__orders.is_test_order: NOT NULL
- stg_shopify__orders.order_amount: NOT NULL
- stg_shopify__orders.order_id: NOT NULL, UNIQUE (primary key)
- stg_shopify__orders.ordered_at: NOT NULL
- fct_orders.customer_id -> dim_customers.customer_id (MANY_TO_ONE join verified)
- stg_demopos__receipts.customer_id -> stg_demopos__customers.customer_id (MANY_TO_ONE join verified)
- stg_shopify__order_lines.order_id -> stg_shopify__orders.order_id (MANY_TO_ONE join verified)

## Relationships

- fct_orders -> dim_customers (MANY_TO_ONE)
- stg_demopos__receipts -> stg_demopos__customers (MANY_TO_ONE)
- stg_shopify__order_lines -> stg_shopify__orders (MANY_TO_ONE)

## Data Quality Warnings

- fct_orders: expression_is_true unknown

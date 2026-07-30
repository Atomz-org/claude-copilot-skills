{{ config(materialized='ephemeral') }}

{{ erp_union('fact_purchase_orders') }}

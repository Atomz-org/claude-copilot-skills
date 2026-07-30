{{ config(materialized='ephemeral') }}

{{ erp_union('fact_budgets') }}

{{ config(materialized='ephemeral') }}

{{ erp_union('dim_cost_centers') }}

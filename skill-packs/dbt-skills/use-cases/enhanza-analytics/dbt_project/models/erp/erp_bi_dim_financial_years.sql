{{ config(materialized='ephemeral') }}

{{ erp_union('dim_financial_years') }}

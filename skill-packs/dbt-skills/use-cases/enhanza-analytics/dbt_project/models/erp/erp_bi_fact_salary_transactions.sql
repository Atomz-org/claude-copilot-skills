{{ config(materialized='ephemeral') }}

{{ erp_union('fact_salary_transactions') }}

{{ config(materialized='ephemeral') }}

{{ erp_union('fact_absence_transactions') }}

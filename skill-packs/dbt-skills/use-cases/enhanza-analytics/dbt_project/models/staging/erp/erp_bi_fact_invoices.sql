{{ config(materialized='ephemeral') }}

{{ erp_union('fact_invoices') }}

{{ config(materialized='ephemeral') }}

{{ erp_union('fact_invoice_rows') }}

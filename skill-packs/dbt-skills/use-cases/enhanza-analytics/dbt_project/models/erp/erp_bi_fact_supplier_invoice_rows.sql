{{ config(materialized='ephemeral') }}

{{ erp_union('fact_supplier_invoice_rows') }}

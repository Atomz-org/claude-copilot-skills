{{ config(materialized='ephemeral') }}

{{ erp_union('dim_supplier_invoice_files') }}

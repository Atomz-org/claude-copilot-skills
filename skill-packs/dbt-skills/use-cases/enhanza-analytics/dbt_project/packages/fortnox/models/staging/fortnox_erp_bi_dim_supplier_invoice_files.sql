{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select *
  , {{ add_erp_fields(columns=['OrgId', 'SupplierInvoiceId']) }}
from {{ ref('fortnox_bi_dim_supplier_invoice_files_staging') }}
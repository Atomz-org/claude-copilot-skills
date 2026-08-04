{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  InvoiceDate
  , DueDate
  , DueStatus
  , FinalPayDate
  , SupplierInvoiceNo
  , InvoiceNumber
  , Currency
  , Total
  , Vat
  , AdministrationFee
  , Freight
  , Balance
  , isCredit
  , isBooked
  , DisablePaymentFile
  , YourReference
  , OurReference
  , OrgId
  , SupplierInvoiceId
  , SupplierId
  , CostCenterId
  , ProjectId
  , {{ add_erp_fields(columns=['OrgId', 'SupplierInvoiceId', 'SupplierId', 'CostCenterId', 'ProjectId']) }}
from {{ ref('fortnox_bi_fact_supplier_invoices_staging') }}
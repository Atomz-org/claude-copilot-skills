{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  InvoiceDate
  , DueDate
  , FinalPayDate
  , SupplierInvoiceNo
  , InvoiceNumber
  , Currency
  , CurrencyRate
  , isCredit
  , isBooked
  , ArticleNumber
  , Account
  , Balance
  , Quantity
  , Price
  , Total
  , Code
  , TransactionInformation
  , Unit
  , YourReference
  , OrgId
  , SupplierInvoiceId
  , SupplierId
  , ArticleId
  , AccountId
  , ProjectId
  , CostCenterId
  , {{ add_erp_fields(columns=['OrgId', 'SupplierInvoiceId', 'SupplierId', 'ArticleId', 'AccountId', 'ProjectId', 'CostCenterId']) }}
from {{ ref('fortnox_bi_fact_supplier_invoice_rows_staging') }}
{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  InvoiceNo
  , InvoiceId
  , InvoiceDate
  , OurReference
  , AccountNumber
  , ArticleNumber
  , DeliveredQuantity
  , Unit
  , PriceBeforeDiscount
  , Discount
  , DiscountType
  , PriceAfterDiscount
  , SalesValue
  , ContributionValue
  , InvoiceType
  , InvoicePeriodStart
  , InvoicePeriodEnd
  , ContractReference
  , YourOrderNumber
  , TermsOfDelivery
  , TermsOfPayment
  , OrgId
  , {{ add_erp_fields(columns=['OrgId', 'InvoiceId', 'ArticleId', 'CustomerId', 'CostCenterId', 'ProjectId', 'FinancialYearId', 'AccountId']) }}
from {{ ref('fortnox_bi_fact_invoice_rows_staging') }}
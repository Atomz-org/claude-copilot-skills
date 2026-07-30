{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  OrderNum
  , OrderId
  , OrderDate
  , DeliveryDate
  , OurReference
  , Currency
  , ArticleNumber
  , Description
  , OrderedQuantity
  , DeliveredQuantity
  , isVATIncluded
  , PriceBeforeDiscount
  , Discount
  , DiscountType
  , PriceAfterDiscount
  , SalesValue
  , OrderedValue
  , ContributionValue
  , VAT
  , InvoiceReference
  , TermsOfDelivery
  , TermsOfPayment
  , OrgId
  , ArticleId
  , CustomerId
  , AccountId
  , CostCenterId
  , ProjectId
  , {{ add_erp_fields(columns=['OrderId', 'OrgId', 'ArticleId','CustomerId', 'AccountId', 'ProjectId', 'CostCenterId']) }}
from {{ ref('fortnox_bi_fact_order_rows_staging') }}
{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  TransactionDate
  , Account
  , Balance as Amount
  , Description
  , cast(DescriptionRows as STRING) as DescriptionRows
  , cast(TransactionInformation as STRING) as TransactionInformation
  , VoucherSeries
  , VoucherNumber
  , AccountClass
  , ReferenceNumber
  , ReferenceType
  , OrgId
  , FinancialYearId
  , AccountId
  , CostCenterId
  , ProjectId
  , VoucherSeriesId
  , cast(null as STRING) as VoucherId
  , CustomerId
  , SupplierId
, {{ add_erp_fields(columns=['OrgId', 'FinancialYearId', 'AccountId', 'CostCenterId', 'ProjectId']) }}
from {{ ref('fortnox_bi_fact_vouchers_staging') }}
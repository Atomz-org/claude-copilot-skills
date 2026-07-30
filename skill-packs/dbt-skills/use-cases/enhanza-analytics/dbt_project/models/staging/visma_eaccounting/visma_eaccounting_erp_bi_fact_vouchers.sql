{{ config(materialized='ephemeral', enabled = var('is_visma_eaccounting_enabled', false)) }}

with fy as ( --fiscalyears source snapshot
  SELECT
    OrgId || '-' || Id FinancialYearId
    , StartDate FromDate
    , EndDate ToDate
    , OrgId
  FROM
    {{ source('visma_eaccounting_api', 'fiscalyears') }}
),

pre_calc as (
  select
    date(v.VoucherDate) TransactionDate
    , cast(json_extract_scalar(r, '$.AccountNumber') as numeric) Account
    , cast(json_extract_scalar(r, '$.CreditAmount') as numeric)-cast(json_extract_scalar(r, '$.DebitAmount') as numeric) Amount
    , v.VoucherText Description
    , cast(json_extract_scalar(r, '$.AccountDescription') as STRING) as DescriptionRows
    , json_extract_scalar(r, '$.TransactionText') TransactionInformation
    , v.NumberSeries VoucherSeries
    , cast(replace(v.NumberAndNumberSeries, v.NumberSeries, '') as int64) VoucherNumber
    , cast(null as INT64) AccountClass
    , cast(null as STRING) as ReferenceNumber
    , cast(null as STRING) as ReferenceType
    , cast(v.OrgId as string) as OrgId
    , fy.FinancialYearId
    , fy.FinancialYearId || '-' || json_extract_scalar(r, '$.AccountNumber') AccountId
    , v.OrgId || '-' || json_extract_scalar(r, '$.CostCenterItemId1') CostCenterId
    , v.OrgId || '-' || json_extract_scalar(r, '$.ProjectId') ProjectId
    , cast(null as STRING) as VoucherSeriesId
    , v.OrgId || '-' || v.Id VoucherId
    , cast(null as STRING) as CustomerId
    , cast(null as STRING) as SupplierId
  from
    {{ source('visma_eaccounting_api', 'vouchers') }} v
    , UNNEST(CAST(JSON_EXTRACT_ARRAY(v.Rows) AS ARRAY<JSON>)) r
    left join fy
      on v.OrgId = fy.OrgId
      and v.VoucherDate between fy.FromDate and fy.ToDate
)

select
  *
, {{ add_erp_fields(columns=['OrgId', 'FinancialYearId', 'AccountId', 'CostCenterId', 'ProjectId']) }}
from
  pre_calc
order by 1 desc, 2
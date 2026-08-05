{{ config(materialized='ephemeral', enabled = var('is_visma_economic_enabled', false)) }}

with part1_pre_calc as (
  select
    date(date) TransactionDate
    , int64(json_extract(account, '$.accountNumber')) Account
    , cast(amountInBaseCurrency as float64) Balance
    , cast(null as string) Description
    , text DescriptionRows
    , cast(null as STRING) as TransactionInformation
    , cast(null as STRING) as VoucherSeries
    , voucherNumber VoucherNumber
    , cast(null as INT64) as AccountClass
    , cast(invoiceNumber as string) ReferenceNumber
    , upper(replace(entryType, ' ', '')) ReferenceType
    , cast(e.OrgId as string) as OrgId
    , e.OrgId || '-' || ay.year FinancialYearId
    , e.OrgId || '-' || ay.year || '-' || json_extract_scalar(account, '$.accountNumber') AccountId
    , cast(null as STRING) as CostCenterId
    , cast(null as STRING) as ProjectId
    , cast(null as STRING) as VoucherSeriesId
    , cast(null as STRING) as VoucherId
    , cast(null as STRING) as CustomerId
    , cast(null as STRING) as SupplierId
  from {{ source('visma_economic_api', 'entries') }} e
  left join {{ source('visma_economic_api', 'accounting_years') }} ay
    on e.OrgId = ay.OrgId
    and e.date between date(ay.fromDate) and date(ay.toDate)
),

part1_final as (
  select
    *
    , {{ add_erp_fields(columns=['OrgId', 'FinancialYearId', 'AccountId']) }}
    , cast(null as STRING) as CostCenterIdERP
    , cast(null as STRING) as ProjectIdERP
  from part1_pre_calc
),

part2_pre_calc as (
  select
    date(json_extract_scalar(e, '$.date')) TransactionDate
    , int64(coalesce(json_extract(e, '$.account.accountNumber'), json_extract(e, '$.contraAccount.accountNumber'))) Account
    , float64(json_extract(e, '$.amountDefaultCurrency')) Balance
    , 'Journal number ' || journalNumber || ': ' || j.name Description
    , cast(json_extract_scalar(e, '$.text') as STRING) DescriptionRows
    , cast(null as STRING) as TransactionInformation
    , cast(null as STRING) as VoucherSeries
    , int64(json_extract(e, '$.voucher.voucherNumber')) VoucherNumber
    , cast(null as INT64) as AccountClass
    , if(regexp_contains(json_extract_scalar(e, '$.text'), r"#\d+"), regexp_extract(json_extract_scalar(e, '$.text'), r"#(\d+)\b"), null) ReferenceNumber
    , upper(replace(json_extract_scalar(e, '$.entryType'), ' ', '')) ReferenceType
    , cast(j.OrgId as string) as OrgId
    , j.OrgId || '-' || json_extract_scalar(e, '$.voucher.accountingYear.year') FinancialYearId
    , j.OrgId || '-' || json_extract_scalar(e, '$.voucher.accountingYear.year') || '-' || coalesce(json_extract_scalar(e, '$.account.accountNumber'), json_extract_scalar(e, '$.contraAccount.accountNumber')) AccountId
    , cast(null as STRING) as CostCenterId
    , cast(null as STRING) as ProjectId
    , cast(null as STRING) as VoucherSeriesId
    , cast(null as STRING) as VoucherId
    , cast(null as STRING) as CustomerId
    , cast(null as STRING) as SupplierId
  from {{ source('visma_economic_api', 'journals') }} j
    , unnest(json_extract_array(entries)) e
),

part2_final as (
  select
    *
    , {{ add_erp_fields(columns=['OrgId', 'FinancialYearId', 'AccountId']) }}
    , cast(null as STRING) as CostCenterIdERP
    , cast(null as STRING) as ProjectIdERP
  from part2_pre_calc
)

select * from part1_final
union all
select * from part2_final
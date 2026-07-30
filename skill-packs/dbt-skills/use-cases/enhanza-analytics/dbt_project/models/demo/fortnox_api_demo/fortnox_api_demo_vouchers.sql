{{ config(alias=(model_alias(model.name))) }}


with org as (
  select
    min(OrgId) OrgId
  from {{ source('fortnox_api_demo', 'vouchers') }}
)
, cstcntr as (
  select
    Code
    , row_number() over(order by Code asc) rn
  from {{ source('fortnox_api_demo', 'cost_centers') }}
  where OrgId = (select OrgId from org)
  group by 1
)
, prjct as (
  select
    ProjectNumber
    , row_number() over(order by ProjectNumber asc) rn
  from {{ source('fortnox_api_demo', 'projects') }}
  where OrgId = (select OrgId from org)
  group by 1
)
, invoice_no as (
  select
    DocumentNumber
    , row_number() over(order by DocumentNumber asc) rn
  from {{ source('fortnox_api_demo', 'v2_invoices') }}
  where OrgId = (select OrgId from org)
    and extract(year from InvoiceDate) in (extract(year from current_date()) - 1, extract(year from current_date()) - 2)
  group by 1
)
select
  '1111111111' OrgId
  , cast(null as string) Comments
  , cast(cstcntr.rn * 100 as string) CostCenter
  , cast(null as string) Description
  , cast(prjct.rn * 100 as string) `Project`
  , cast(invoice_no.DocumentNumber as string) ReferenceNumber
  , ReferenceType
  , {{ demo_date('TransactionDate') }} TransactionDate
  , VoucherNumber * ({{ var('demo_multi', 2) }} - 1) VoucherNumber
  , VoucherSeries
  , Year
  , 0 ApprovalState
  , array(select struct(
    r.Account
    , cast(cstcntr2.rn * 100 as string) as CostCenter
    , r.Credit
    , cast(null as string) as Description
    , r.Debit
    , cast(prjct2.rn * 100 as string) as `Project`
    , r.Removed
    , cast(null as string) as TransactionInformation
  )) VoucherRows
  , current_timestamp() ENZ_CREATED_AT
  , cast(null as timestamp) ENZ_MODIFIED_AT
  , current_timestamp() ENZ_SYNC_TS
  , 'Success' ENZ_DEBUG_INFO
from {{ source('fortnox_api_demo', 'vouchers') }} v
cross join unnest(v.VoucherRows) r
left join cstcntr
  on cstcntr.Code = v.CostCenter
left join prjct
  on prjct.ProjectNumber = v.Project
left join cstcntr cstcntr2
  on cstcntr2.Code = r.CostCenter
left join prjct prjct2
  on prjct.ProjectNumber = r.Project
left join invoice_no
  on cast(invoice_no.DocumentNumber as string) = v.ReferenceNumber
  and v.ReferenceType = 'INVOICE'
where v.OrgId = (select OrgId from org)
  and extract(year from TransactionDate) in ( 
    {{ global_configs('demo_max_year') }}
    , {{ global_configs('demo_max_year') }} - 1 
  )
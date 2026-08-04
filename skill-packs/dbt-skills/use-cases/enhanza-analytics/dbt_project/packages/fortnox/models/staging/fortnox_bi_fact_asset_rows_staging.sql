{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  OrgId || '-' || Id AssetId
  , Status
  , Type AssetType
  , cast(json_extract_scalar(r, '$.Amount') as float64) Amount
  , date(json_extract_scalar(r, '$.Date')) `Date`
  , json_extract_scalar(r, '$.Notes') Notes
  , json_extract_scalar(r, '$.UserName') CreatedBy
  , json_extract_scalar(r, '$.VoucherNumber') VoucherNumber
  , json_extract_scalar(r, '$.VoucherSeries') VoucherSeries
  , OrgId
  , case
    when json_extract_scalar(r, '$.SupplierInvoice') <> '0'
      then OrgId || '-' || json_extract_scalar(r, '$.SupplierInvoice') 
    else cast(null as string)
  end SupplierInvoiceId
  , OrgId || '-' || json_extract_scalar(r, '$.EventId') EventId
  , OrgId || '-' || json_extract_scalar(r, '$.VoucherYear') FinancialYearId
  , OrgId || '-' || CostCenter CostCenterId
  , OrgId || '-' || `Project` ProjectId
from {{ source('fortnox_api', 'assets') }} a
, unnest(json_extract_array(History)) r
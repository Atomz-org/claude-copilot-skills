{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select  
  OrgId
  , cast(AccrualAccount as INT64) AccrualAccount
  , cast(costAccount as INT64) CostAccount
  , OrgId || '-' || supplierInvoiceNumber SupplierInvoiceId
  , Total Net
  , date(StartDate) StartDate
  , date(EndDate) EndDate
  , Period
  , Times NumberOfPayments
  , OrgId || '-' || max( {{ blank_to_null("json_extract_scalar(r, '$.CostCenter')") }} ) CostCenterId
  , OrgId || '-' || max( {{ blank_to_null("json_extract_scalar(r, '$.Project')") }} ) ProjectId
from {{ source('fortnox_api', 'supplier_invoice_accruals') }}
, unnest(json_extract_array(SupplierInvoiceAccrualRows)) r
group by 1,2,3,4,5,6,7,8,9
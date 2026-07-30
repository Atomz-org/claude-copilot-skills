{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

SELECT
  OrgId
  , parse_numeric(AccrualAccount) AccountNumber
--there is no "ID" column in Accounts dim, so Account "Number" for readability
  , OrgId || '-' || {{ blank_to_null('InvoiceNumber') }} InvoiceId
  , Total Net
  , StartDate
  , EndDate
  , Period
  , Times NumberOfPayments
  , OrgId || '-' || max( {{ blank_to_null("json_extract_scalar(r, '$.CostCenter')") }} ) CostCenterId
  , OrgId || '-' || max( {{ blank_to_null("json_extract_scalar(r, '$.Project')") }} ) ProjectId 
FROM {{ source('fortnox_api', 'invoice_accruals') }}
, unnest(json_extract_array(InvoiceAccrualRows)) r
group by 1,2,3,4,5,6,7,8
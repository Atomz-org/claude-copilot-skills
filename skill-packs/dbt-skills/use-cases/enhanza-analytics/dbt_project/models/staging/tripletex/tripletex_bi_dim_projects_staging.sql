{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

--check on real data for hierarchy levels!
select
  OrgId || '-' || id ProjectId
  , trim(`number`) ProjectNumber
  , trim(description) Description
  , date(startDate) Startdate
  , date(endDate) EndDate
  --   , Comments unavailable
  , json_extract_scalar(contact, '$.displayName') ContactPerson
  , json_extract_scalar(projectManager, '$.displayName') ProjectLeader
  , case
    when isClosed then 'Closed'
    when isReadyForInvoicing then 'Ready for invoicing'
    when isOffer then 'Offer'
    else 'N/A'
  end Status
from {{ source('tripletex_api', 'project') }}
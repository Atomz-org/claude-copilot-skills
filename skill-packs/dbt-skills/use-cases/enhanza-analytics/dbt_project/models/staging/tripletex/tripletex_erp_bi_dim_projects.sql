{{ config(materialized='ephemeral', enabled = var('is_tripletex_enabled', false)) }}

with main as (
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
)
select
  ProjectId
  , ProjectNumber
  , Description
  , Startdate
  , EndDate
  , cast(null as STRING) as Comments
  , ContactPerson
  , ProjectLeader
  , Status
  , {{ add_erp_fields(columns=['ProjectId']) }}
from main
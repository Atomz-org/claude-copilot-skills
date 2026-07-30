{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name) ) }}

select
  id OpportunityNo
  , date(date) OpportunityDate
  , if(closeDate is null, TRUE, FALSE) isClosed
  , json_extract_scalar(stage, '$.name') Stage
  , date(closeDate) FinalCloseDate
  , date(confirmedDate) ConfirmedDate
  , json_extract_scalar(user, '$.name') OurReference
  , currency Currency
  , currencyRate CurrencyRate
  , value * currencyRate Net
  , contributionMargin * currencyRate Contribution
  , purchaseCost * currencyRate PurchaseCost
  , confirmedBudget * currencyRate Budget
  , notes Comments
  , description Remarks
  , OrgId
  , OrgId || '-' || id OpportunityId
  , OrgId || '-' || json_extract_scalar(client, '$.id') CustomerId
  , OrgId || '-' || extract(year from date) FinancialYearId

  -- , json_extract_scalar(contact, '$.email') ContactEmail
  -- , OrgId || '-' || json_extract_scalar(project, '$.id') ProjectId
  -- , json_extract_scalar(project, '$.name') ProjectName
  -- , probability Probability
  
from {{ source('upsales_api', 'opportunities') }}
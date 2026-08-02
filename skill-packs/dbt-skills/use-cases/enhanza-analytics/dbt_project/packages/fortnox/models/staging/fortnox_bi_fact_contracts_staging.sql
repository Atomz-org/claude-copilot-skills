{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  DocumentNumber
  , ContractDate
  , ContractLength
  , PeriodStart
  , PeriodEnd
  , InvoiceInterval
  , InvoicesRemaining
  , Currency
  , AdministrationFee
  , Freight
  , Gross
  , Net
  , ContributionValue
  , RoundOff
  , TaxReduction
  , Total
  , TotalToPay
  , TotalVAT
  , ContributionPercent
  , HouseWork
  , TaxReductionType
  , Continuous
  , Status
  , Remarks Note
  , trim(TemplateName) TemplateName
  , TemplateNumber
  , {{ blank_to_null('TermsOfDelivery') }} TermsOfDelivery
  , {{ blank_to_null('TermsOfPayment') }} TermsOfPayment
  , {{ blank_to_null('WayOfDelivery') }} WayOfDelivery
  , {{ blank_to_null('YourOrderNumber') }} YourOrderNumber
  , initcap( {{ blank_to_null('OurReference') }} ) OurReference
  , {{ blank_to_null('YourReference') }} YourReference
  , c.OrgId
  , c.OrgId || '-' || DocumentNumber ContractId
  , c.OrgId || '-' || {{ blank_to_null('CustomerNumber') }} CustomerId
  -- VoucherYear should be included in AccountId since Account details vary per year. But VoucherYear is not set/available until the invoices is booked.
  , c.OrgId || '-' || {{ blank_to_null('CostCenter') }} CostCenterId
  , c.OrgId || '-' || {{ blank_to_null('Project') }} ProjectId
  , c.OrgId || '-' || {{ blank_to_null('PriceList') }} PriceListId
from {{ source('fortnox_api', 'contracts') }} c
where c.Active is not FALSE
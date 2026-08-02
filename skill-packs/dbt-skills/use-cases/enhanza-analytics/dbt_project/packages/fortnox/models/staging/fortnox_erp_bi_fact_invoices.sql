{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
  InvoiceNo
  , InvoiceId
  , InvoiceDate
  , OutboundDate
  , DeliveryDate
  , DueDate
  , IsDue
  , DueStatus
  , FinalPayDate
  , Reminders
  , LastRemindDate
  , isCredit
  , OurReference
  , YourReference
  , YourOrderNumber
  , Sent
  , Currency
  , CurrencyRate
  , Gross
  , Net
  , Freight
  , AdministrationFee
  , TotalVAT
  , TotalToPay
  , Balance
  , RoundOff
  , Total
  , HouseWork
  , ContributionValue
  , Comments
  , Remarks
  , TermsOfDelivery
  , TermsOfPayment
  , WayOfDelivery
  , DeliveryAddress1
  , DeliveryAddress2
  , DeliveryCity
  , DeliveryCountry
  , DeliveryZipCode
  , DeliveryName
  , RecipientEmail
  , RecipientPhone
  , Country
  , ExternalInvoiceReference1
  , ExternalInvoiceReference2
  , CreditInvoiceReference
  , InvoiceOCR
  , OfferReference
  , OrderReference
  , ContractReference
  , isWarehouseReady
  , Labels
  , OrgId
  , CustomerId
  , FinancialYearId
  , CostCenterId
  , ProjectId
  , PriceList
  , {{ add_erp_fields(columns=['OrgId', 'InvoiceId', 'CustomerId', 'FinancialYearId', 'CostCenterId', 'ProjectId']) }}
from {{ ref('fortnox_bi_fact_invoices_staging') }}
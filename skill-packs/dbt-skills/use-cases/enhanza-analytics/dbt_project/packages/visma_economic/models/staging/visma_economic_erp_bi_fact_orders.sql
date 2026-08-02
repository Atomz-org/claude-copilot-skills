{{ config(materialized='ephemeral', enabled = var('is_visma_economic_enabled', false)) }}

with e as (
  select
    OrgId || '-' || employeeNumber as EmployeeId
    , name as OurReference
  from {{ source('visma_economic_api', 'employees') }}
)
, archive as (
  select
    orderNumber as OrderNo
    , OrgId || '-' || orderNumber as OrderId
    , cast(null as STRING) as InvoiceReference
    , cast(null as STRING) as OfferReference
    , date(date) as OrderDate
    , cast(null as DATE) as OutboundDate
    , 'Order' as OrderType
    , date(json_extract_scalar(delivery, '$.deliveryDate')) as DeliveryDate
    , cast(null as STRING) as DeliveryState
    , e.OurReference
    , cast(null as STRING) as YourOrderNumber
    , cast(null as STRING) as YourReference
    , cast(null as BOOLEAN) as Sent
    , cast(null as BOOLEAN) as NotCompleted
    , cast(null as BOOLEAN) as HouseWork
    , currency as Currency
    , exchangeRate as CurrencyRate
    , cast(null as FLOAT64) as Freight
    , cast(null as FLOAT64) as AdministrationFee
    , vatAmount * coalesce(exchangeRate, 1) as TotalVAT
    , netAmountInBaseCurrency as Net
    , cast(null as FLOAT64) as TaxReduction
    , grossAmountInBaseCurrency as Gross
    , roundingAmount * coalesce(exchangeRate, 1) as RoundOff
    , netAmountInBaseCurrency + (vatAmount + roundingAmount) * coalesce(exchangeRate, 1) as TotalToPay
    , marginPercentage as ContributionPercent
    , marginInBaseCurrency as ContributionValue
    , cast(null as STRING) as TermsOfDelivery
    , cast(null as STRING) as TermsOfPayment
    , cast(null as STRING) as WayOfDelivery
    , cast(null as STRING) as DeliveryAddress1
    , cast(null as STRING) as DeliveryAddress2
    , cast(null as STRING) as DeliveryCity
    , cast(null as STRING) as DeliveryCountry
    , cast(null as STRING) as DeliveryZipCode
    , cast(null as STRING) as DeliveryName
    , cast(null as STRING) as RecipientEmail
    , cast(null as STRING) as RecipientPhone
    , cast(null as STRING) as Comments
    , cast(null as BOOLEAN) as hasCopyRemarks
    , cast(null as STRING) as ExternalInvoiceReference1
    , cast(null as STRING) as ExternalInvoiceReference2
    , cast(null as STRING) as Country
    , cast(null as BOOLEAN) as isWarehouseReady
    , cast(null as STRING) as Labels
    , cast(OrgId as string) as OrgId
    , OrgId || '-' || json_extract_scalar(customer, '$.customerNumber') as CustomerId
    , cast(null as STRING) as StockPointId
    , cast(null as STRING) as LabelId
  from {{ source('visma_economic_api', 'orders_archived') }} o
  left join e
    on e.EmployeeId = o.OrgId || '-' || json_extract_scalar(references, '$.salesPerson.employeeNumber')
    where OrgId || '-' || orderNumber not in (
      select
        distinct OrgId || '-' || orderNumber
      from {{ source('visma_economic_api', 'orders_sent') }}
    )
)
, drafts as (
  select
    orderNumber as OrderNo
    , OrgId || '-' || orderNumber as OrderId
    , cast(null as STRING) as InvoiceReference
    , cast(null as STRING) as OfferReference
    , date(date) as OrderDate
    , cast(null as DATE) as OutboundDate
    , 'Order' as OrderType
    , date(json_extract_scalar(delivery, '$.deliveryDate')) as DeliveryDate
    , cast(null as STRING) as DeliveryState
    , e.OurReference
    , cast(null as STRING) as YourOrderNumber
    , cast(null as STRING) as YourReference
    , cast(null as BOOLEAN) as Sent
    , TRUE as NotCompleted
    , cast(null as BOOLEAN) as HouseWork
    , currency as Currency
    , exchangeRate as CurrencyRate
    , cast(null as FLOAT64) as Freight
    , cast(null as FLOAT64) as AdministrationFee
    , vatAmount * coalesce(exchangeRate, 1) as TotalVAT
    , netAmountInBaseCurrency as Net
    , cast(null as FLOAT64) as TaxReduction
    , grossAmountInBaseCurrency as Gross
    , roundingAmount * coalesce(exchangeRate, 1) as RoundOff
    , netAmountInBaseCurrency + (vatAmount + roundingAmount) * coalesce(exchangeRate, 1) as TotalToPay
    , marginPercentage as ContributionPercent
    , marginInBaseCurrency as ContributionValue
    , cast(null as STRING) as TermsOfDelivery
    , cast(null as STRING) as TermsOfPayment
    , cast(null as STRING) as WayOfDelivery
    , cast(null as STRING) as DeliveryAddress1
    , cast(null as STRING) as DeliveryAddress2
    , cast(null as STRING) as DeliveryCity
    , cast(null as STRING) as DeliveryCountry
    , cast(null as STRING) as DeliveryZipCode
    , cast(null as STRING) as DeliveryName
    , cast(null as STRING) as RecipientEmail
    , cast(null as STRING) as RecipientPhone
    , cast(null as STRING) as Comments
    , cast(null as BOOLEAN) as hasCopyRemarks
    , cast(null as STRING) as ExternalInvoiceReference1
    , cast(null as STRING) as ExternalInvoiceReference2
    , cast(null as STRING) as Country
    , cast(null as BOOLEAN) as isWarehouseReady
    , cast(null as STRING) as Labels
    , cast(OrgId as string) as OrgId
    , OrgId || '-' || json_extract_scalar(customer, '$.customerNumber') as CustomerId
    , cast(null as STRING) as StockPointId
    , cast(null as STRING) as LabelId
  from {{ source('visma_economic_api', 'orders_drafts') }} o
  left join e
    on e.EmployeeId = o.OrgId || '-' || json_extract_scalar(references, '$.salesPerson.employeeNumber')
)
, sent as (
  select
    orderNumber as OrderNo
    , OrgId || '-' || orderNumber as OrderId
    , cast(null as STRING) as InvoiceReference
    , cast(null as STRING) as OfferReference
    , date(date) as OrderDate
    , cast(null as DATE) as OutboundDate
    , 'Order' as OrderType
    , date(json_extract_scalar(delivery, '$.deliveryDate')) as DeliveryDate
    , cast(null as STRING) as DeliveryState
    , e.OurReference
    , cast(null as STRING) as YourOrderNumber
    , cast(null as STRING) as YourReference
    , TRUE as Sent
    , cast(null as BOOLEAN) as NotCompleted
    , cast(null as BOOLEAN) as HouseWork
    , currency as Currency
    , exchangeRate as CurrencyRate
    , cast(null as FLOAT64) as Freight
    , cast(null as FLOAT64) as AdministrationFee
    , vatAmount * coalesce(exchangeRate, 1) as TotalVAT
    , netAmountInBaseCurrency as Net
    , cast(null as FLOAT64) as TaxReduction
    , grossAmountInBaseCurrency as Gross
    , roundingAmount * coalesce(exchangeRate, 1) as RoundOff
    , netAmountInBaseCurrency + (vatAmount + roundingAmount) * coalesce(exchangeRate, 1) as TotalToPay
    , marginPercentage as ContributionPercent
    , marginInBaseCurrency as ContributionValue
    , cast(null as STRING) as TermsOfDelivery
    , cast(null as STRING) as TermsOfPayment
    , cast(null as STRING) as WayOfDelivery
    , cast(null as STRING) as DeliveryAddress1
    , cast(null as STRING) as DeliveryAddress2
    , cast(null as STRING) as DeliveryCity
    , cast(null as STRING) as DeliveryCountry
    , cast(null as STRING) as DeliveryZipCode
    , cast(null as STRING) as DeliveryName
    , cast(null as STRING) as RecipientEmail
    , cast(null as STRING) as RecipientPhone
    , cast(null as STRING) as Comments
    , cast(null as BOOLEAN) as hasCopyRemarks
    , cast(null as STRING) as ExternalInvoiceReference1
    , cast(null as STRING) as ExternalInvoiceReference2
    , cast(null as STRING) as Country
    , cast(null as BOOLEAN) as isWarehouseReady
    , cast(null as STRING) as Labels
    , cast(OrgId as string) as OrgId
    , OrgId || '-' || json_extract_scalar(customer, '$.customerNumber') as CustomerId
    , cast(null as STRING) as StockPointId
    , cast(null as STRING) as LabelId
  from {{ source('visma_economic_api', 'orders_sent') }} o
  left join e
    on e.EmployeeId = o.OrgId || '-' || json_extract_scalar(references, '$.salesPerson.employeeNumber')
)
, final as (
  select * from drafts
    union all
  select * from archive
    union all
  select * from sent
)
select *
  , {{ add_erp_fields(columns=['OrderId', 'OrgId', 'LabelId','CustomerId', 'StockPointId']) }}
from final
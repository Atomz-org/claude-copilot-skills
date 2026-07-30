{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}


with labels0 as (
  select 
    i.OrgId
    , i.DocumentNumber
    , trim(l.Description) || ' (' || l.Id || ')' Label
  from {{ source('fortnox_api', 'v2_orders') }} i
  , unnest(json_extract_array(Labels)) r
  left join {{ source('fortnox_api', 'labels') }} l
    on l.OrgId = i.OrgId
    and cast(l.Id as string) = json_extract_scalar(r, '$.Id')
  where l.Id is not null
)

, labels as (
  select
    OrgId
    , DocumentNumber
    , string_agg(Label, ', ') Labels
  from labels0
  group by 1,2
)

select
  cast(o.DocumentNumber as int64) OrderNo
  , o.OrgId || '-' || o.DocumentNumber OrderId
  , InvoiceReference
  , OfferReference
  , date(OrderDate) OrderDate
  , date(OutboundDate) OutboundDate
  , OrderType
  , DeliveryDate
  , trim(initcap(DeliveryState)) DeliveryState
  , initcap( {{ blank_to_null('OurReference') }} ) OurReference
  , trim({{ blank_to_null('YourOrderNumber') }}) YourOrderNumber
  , trim({{ blank_to_null('YourReference') }}) YourReference
  , Sent
  , NotCompleted
  , HouseWork
  , Currency
  , CurrencyRate
  , Freight * CurrencyRate Freight
  , AdministrationFee * CurrencyRate AdministrationFee
  , TotalVAT * CurrencyRate TotalVAT
  , Net * CurrencyRate Net
  , TaxReduction
  , Gross * CurrencyRate Gross
  , RoundOff * CurrencyRate RoundOff
  , TotalToPay * CurrencyRate TotalToPay
  , ContributionPercent
  , ContributionValue
  , {{ blank_to_null("TermsOfDelivery") }} TermsOfDelivery
  , {{ blank_to_null("TermsOfPayment") }} TermsOfPayment
  , {{ blank_to_null("TermsOfPayment") }} WayOfDelivery
  , {{ blank_to_null("DeliveryAddress1") }} DeliveryAddress1
  , {{ blank_to_null("DeliveryAddress2") }} DeliveryAddress2
  , {{ blank_to_null("DeliveryCity") }} DeliveryCity
  , {{ blank_to_null("DeliveryCountry") }} DeliveryCountry
  , {{ blank_to_null("DeliveryZipCode") }} DeliveryZipCode
  , {{ blank_to_null("DeliveryName") }} DeliveryName
  , {{ blank_to_null("json_extract_scalar(EmailInformation, '$.EmailAddressTo')") }} RecipientEmail
  , {{ blank_to_null("Phone1") }} RecipientPhone
  , trim({{ blank_to_null('Comments')}}) Comments
  , CopyRemarks hasCopyRemarks
  , ExternalInvoiceReference1
  , ExternalInvoiceReference2
  , trim({{ blank_to_null('Country') }}) Country
  , WarehouseReady isWarehouseReady
  , labels.Labels
  , o.OrgId
  , o.OrgId || '-' || {{ blank_to_null('CustomerNumber') }} CustomerId
  , o.OrgId || '-' || {{ blank_to_null('StockPointCode') }} StockPointId
  , cast(null as string) LabelId
from {{ source('fortnox_api', 'v2_orders') }} o
left join labels
  on labels.OrgId = o.OrgId
  and labels.DocumentNumber = o.DocumentNumber
where
  cancelled is not true
  and OrderDate > date_sub(current_date(), interval 5 year)
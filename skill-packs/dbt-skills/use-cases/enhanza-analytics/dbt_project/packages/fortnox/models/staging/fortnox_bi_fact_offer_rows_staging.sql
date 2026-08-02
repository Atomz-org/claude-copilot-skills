{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
    DocumentNumber OfferNo
    , o.OrgId || '-' || DocumentNumber OfferId
    , date(OfferDate) OfferDate
    , {{ blank_to_null('OurReference') }} OurReference
    , Currency
    , CurrencyRate
    , {{ blank_to_null("json_extract_scalar(r, '$.ArticleNumber')") }} ArticleNumber
    , json_extract_scalar(r, '$.Description') Description
    , cast(json_extract_scalar(r, '$.Quantity') as float64) Quantity
    -- NET prices calculated based on VATincluded, see https://enhanza.atlassian.net/browse/ED-1115
    -- Price before discount calculated as NET-ified price from pricelist
    , VATIncluded isVATIncluded
    , cast(json_extract_scalar(r, '$.Price') as float64) * 
        case
        when o.VATIncluded <> TRUE then 1
        else 1 / (1 + cast(json_extract_scalar(r, '$.VAT') as float64) / 100)
      end 
    * o.CurrencyRate PriceBeforeDiscount
    , cast(json_extract_scalar(r, '$.Discount') as float64) 
      * if (json_extract_scalar(r, '$.DiscountType') = 'PERCENT', 1, o.CurrencyRate) Discount
    , initcap(json_extract_scalar(r, '$.DiscountType')) DiscountType
    -- NET prices calculated based on VATincluded boolean
    -- Price after discount calculated as Total NET / qty, final price
    , cast(json_extract_scalar(r, '$.Total') as float64) * 
      case
        when o.VATIncluded <> TRUE then 1
        else 1 / (1 + cast(json_extract_scalar(r, '$.VAT') as float64) / 100)
      end 
    / nullif(cast(json_extract_scalar(r, '$.Quantity') as float64), 0) * o.CurrencyRate PriceAfterDiscount
    -- SalesValue (NET) calculation based on VATincluded boolean
    , cast(json_extract_scalar(r, '$.Total') as float64) * 
      case
        when o.VATIncluded <> TRUE then 1
        else 1 / (1 + cast(json_extract_scalar(r, '$.VAT') as float64) / 100)
      end 
    * o.CurrencyRate SalesValue
    , cast(json_extract_scalar(r, '$.ContributionValue') as float64) ContributionValue
    , cast(json_extract_scalar(r, '$.VAT') as float64) VAT
    , OrderReference
    , {{ blank_to_null("o.TermsOfDelivery") }} TermsOfDelivery
    , {{ blank_to_null("o.TermsOfPayment") }} TermsOfPayment
    , o.OrgId
    , o.OrgId || '-' || {{ blank_to_null("json_extract_scalar(r, '$.ArticleNumber')") }} ArticleId
    , o.OrgId || '-' || {{ blank_to_null ('o.CustomerNumber') }} CustomerId
    , fy.OrgId || '-' || fy.Id || '-' || if (cast(json_extract_scalar(r, '$.AccountNumber') as int64)=0, null, cast(json_extract_scalar(r, '$.AccountNumber') as int64)) AccountId
    , o.OrgId || '-' || {{ blank_to_null("json_extract_scalar(r, '$.CostCenter')") }} CostCenterId
    , o.OrgId || '-' || {{ blank_to_null("json_extract_scalar(r, '$.Project')") }} ProjectId
from {{ source('fortnox_api', 'v2_offers') }} o
, unnest(json_extract_array(OfferRows)) r
left join {{ source('fortnox_api', 'financial_years') }} fy 
  on date(o.OfferDate) between fy.FromDate and fy.ToDate 
  and fy.OrgId=o.OrgId
where 
    cancelled is not true
    -- filter out rows without price or contribution
    and (length(json_extract_scalar(r, '$.ArticleNumber')) > 0 
    or json_extract_scalar(r, '$.Price') <> '0' or json_extract_scalar(r, '$.ContributionValue') <> '0')
{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}


select
  cast(i.DocumentNumber as int64) InvoiceNo
  , i.OrgId || '-' || i.DocumentNumber InvoiceId
  , date(i.InvoiceDate) InvoiceDate
  , initcap( {{ blank_to_null('i.OurReference') }} ) OurReference
  , i.Currency
  , i.CurrencyRate
  , if(json_extract_scalar(r, '$.AccountNumber') = '0', null, cast(json_extract_scalar(r, '$.AccountNumber') as int64)) AccountNumber
  , {{ blank_to_null("json_extract_scalar(r, '$.ArticleNumber')") }} ArticleNumber
  , {{ blank_to_null("json_extract_scalar(r, '$.Description')") }} Description
  , cast(json_extract_scalar(r, '$.DeliveredQuantity') as float64) DeliveredQuantity
  , {{ blank_to_null("json_extract_scalar(r, '$.Unit')") }} Unit
  , VATIncluded isVATIncluded
  , cast(json_extract_scalar(r, '$.PriceExcludingVAT') as float64) 
    * i.CurrencyRate PriceBeforeDiscount
  , cast(json_extract_scalar(r, '$.Discount') as float64) 
    * if (
      json_extract_scalar(r, '$.DiscountType') = 'PERCENT'
      , 1
      , i.CurrencyRate
    ) Discount
  , initcap(json_extract_scalar(r, '$.DiscountType')) DiscountType
  , round(
      cast(json_extract_scalar(r, '$.TotalExcludingVAT') as float64) 
      / nullif(cast(json_extract_scalar(r, '$.DeliveredQuantity') as float64), 0) 
      * i.CurrencyRate
    , 3) PriceAfterDiscount
  -- r.TotalExcludingVAT replaces previous long calculation with different discounts and quantity.
  , cast(json_extract_scalar(r, '$.TotalExcludingVAT') as float64) 
    * i.CurrencyRate SalesValue
  , cast(json_extract_scalar(r, '$.ContributionValue') as float64) ContributionValue
  , cast(json_extract_scalar(r, '$.VAT') as float64) VAT
  , i.InvoiceType
  , i.InvoicePeriodStart
  , i.InvoicePeriodEnd
  , i.ContractReference
  , {{ blank_to_null("i.YourOrderNumber") }} YourOrderNumber
  , {{ blank_to_null("i.TermsOfDelivery") }} TermsOfDelivery
  , {{ blank_to_null("i.TermsOfPayment") }} TermsOfPayment
  , i.OrgId
  , i.OrgId || '-' || {{ blank_to_null("json_extract_scalar(r, '$.ArticleNumber')") }} ArticleId
  , i.OrgId || '-' || {{ blank_to_null("i.CustomerNumber") }} CustomerId
  -- i.VoucherYear should be included in AccountId since Account details vary per year. But i.VoucherYear is not set/available until the invoices is booked.
  , fy.OrgId || '-' || fy.Id || '-' || if(json_extract_scalar(r, '$.AccountNumber') = '0', null, json_extract_scalar(r, '$.AccountNumber')) AccountId
  , i.OrgId || '-' || {{ blank_to_null("json_extract_scalar(r, '$.CostCenter')") }} CostCenterId
  , i.OrgId || '-' || {{ blank_to_null("json_extract_scalar(r, '$.Project')") }} ProjectId
  , i.OrgId || '-' || i.VoucherYear FinancialYearId
from {{ ref('fortnox_base_v2_invoices') }} i
, unnest(json_extract_array(InvoiceRows)) r
left join {{ source('fortnox_api', 'financial_years') }} fy 
  on date(i.InvoiceDate) between fy.FromDate and fy.ToDate 
  and fy.OrgId=i.OrgId
where
  i.cancelled is not true
  and (length(json_extract_scalar(r, '$.ArticleNumber')) > 0
  -- filter out rows without price or contribution
  or json_extract_scalar(r, '$.Price') <> '0' or json_extract_scalar(r, '$.ContributionValue') <> '0')

  -- Remove the below date filter since dynamic filter like current_date prevent Bigquery cache.
  -- updated with ED-1113
  {# and extract(year from i.InvoiceDate) >= extract(year from current_date()) - 6 #}
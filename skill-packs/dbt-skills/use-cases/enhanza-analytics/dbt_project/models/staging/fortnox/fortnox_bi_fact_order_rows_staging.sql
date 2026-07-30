{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}


-- As calculation gets more complex, a separate CTE is done to separate 
-- data extraction from JSON from data calculations
-- This CTE basically prepares data for calculations
with data_extract as (
  select
    cast(o.DocumentNumber as int64) OrderNum
    , o.OrgId || '-' || o.DocumentNumber OrderId
    , date(o.OrderDate) OrderDate
    , date(o.DeliveryDate) DeliveryDate
    , initcap( {{blank_to_null('o.OurReference') }} ) OurReference
    , o.Currency
    , o.CurrencyRate
    , {{ blank_to_null("json_extract_scalar(r, '$.ArticleNumber')") }} ArticleNumber
    , json_extract_scalar(r, '$.Description') Description
    , cast(json_extract_scalar(r, '$.OrderedQuantity') as float64) OrderedQuantity
    , cast(json_extract_scalar(r, '$.DeliveredQuantity') as float64) DeliveredQuantity
    , o.VATIncluded isVATIncluded
    , cast(json_extract_scalar(r, '$.Price') as float64) Price
    , cast(json_extract_scalar(r, '$.VAT') as float64) VAT
    , cast(json_extract_scalar(r, '$.Discount') as float64) Discount
    , json_extract_scalar(r, '$.DiscountType') DiscountType
    , a.Type
    , a.StockGoods
    , cast(json_extract_scalar(r, '$.ReservedQuantity') as float64) ReservedQuantity
    , cast(json_extract_scalar(r, '$.ContributionValue') as float64) ContributionValue
    , o.InvoiceReference
    , {{ blank_to_null("o.TermsOfDelivery") }} TermsOfDelivery
    , {{ blank_to_null("o.TermsOfPayment") }} TermsOfPayment
    , o.OrgId
    , o.OrgId || '-' || {{ blank_to_null("json_extract_scalar(r, '$.ArticleNumber')") }} ArticleId
    , o.OrgId || '-' || {{ blank_to_null ('o.CustomerNumber') }} CustomerId
    , json_extract_scalar(r, '$.AccountNumber') AccountNumber
    , o.OrgId || '-' || fy.Id FYID
    , o.OrgId || '-' || {{ blank_to_null("json_extract_scalar(r, '$.CostCenter')") }} CostCenterId
    , o.OrgId || '-' || {{ blank_to_null("json_extract_scalar(r, '$.Project')") }} ProjectId
  from
  {{ source('fortnox_api', 'v2_orders') }} o
  , unnest(json_extract_array(OrderRows)) r
  left join {{ source('fortnox_api', 'financial_years') }} fy 
    on date(o.OrderDate) between fy.FromDate and fy.ToDate 
    and fy.OrgId = o.OrgId
  -- Fin years needed for AccountId
  left join  {{ source('fortnox_api', 'articles') }} a
    on a.ArticleNumber = json_extract_scalar(r, '$.ArticleNumber')
    and a.OrgId = o.OrgId
  -- Type and StockGoods columns from articles are needed to distinguish between different order rows
  where
    o.cancelled is not true
    and (length(json_extract_scalar(r, '$.ArticleNumber')) > 0
    -- filter out rows without price or contribution
    or json_extract_scalar(r, '$.Price') <> '0' or json_extract_scalar(r, '$.ContributionValue') <> '0')
    and o.OrderDate > date_sub(current_date(), interval 5 year)
)

, data_pre_calc as (
  select
    OrderNum
    , OrderId
    , OrderDate
    , DeliveryDate
    , OurReference
    , Currency
    , ArticleNumber
    , Description
    , OrderedQuantity
    , DeliveredQuantity
    -- In order_rows, NET price is used, so we need to know if VAT is already included in the price
    , isVATIncluded
    , Price * CurrencyRate
      * case
        when isVATIncluded <> TRUE then 1
        -- if VAT is included in price, we need to exclude it to get NET price
        else 1 / (1 + VAT / 100)
      end 
    PriceBeforeDiscount
    , Discount * if (DiscountType = 'PERCENT', 1, CurrencyRate) Discount
    , initcap(DiscountType) DiscountType

  -- Fortnox Support has confirmed that Total from OrderRows is always based on DeliveredQty
  -- and it doesn't add up to document-level Net variable for some workspaces.
  -- It's been decided under ticket ED-1115 that calculations will not be 'simplified' to using just Total
  -- and instead the below calculatiuons are used to match Net of rows with Net of document.

    , case
    -- depending on below conditions, Delivered OR Reserved quantity is used for Net rows (SalesValue)
      when `Type` = 'SERVICE' 
        or StockGoods = FALSE
        or DeliveredQuantity != 0
        or DeliveredQuantity = OrderedQuantity
        then DeliveredQuantity
      when ReservedQuantity != 0
        then ReservedQuantity
      else 0 --if none of conditions are met, the row is NOT included in Net calculations
      end
      -- multiply chosen quantity by price, see price detailed above
      * (Price * CurrencyRate
      * case
        when isVATIncluded <> TRUE then 1
        else 1 / (1 + VAT / 100)
      end
      - case
        when DiscountType = 'PERCENT'
          then Discount * Price * CurrencyRate / 100
        else 0
      end)
      - case
        when DiscountType = 'AMOUNT'
          then Discount
        else 0
      end
    SalesValue
    , OrderedQuantity
      -- multiply chosen quantity by price, see price detailed above
      * (Price * CurrencyRate
      * case
        when isVATIncluded <> TRUE then 1
        else 1 / (1 + VAT / 100)
      end
      - case
        when DiscountType = 'PERCENT'
          then Discount * Price * CurrencyRate / 100
        else 0
      end)
      - case
        when DiscountType = 'AMOUNT'
          then Discount
        else 0
      end
    OrderedValue
    , case
    -- depending on below conditions, Delivered OR Reserved quantity is used for Net rows (SalesValue)
      when `Type` = 'SERVICE' 
        or StockGoods = FALSE
        or DeliveredQuantity != 0
        or DeliveredQuantity = OrderedQuantity
        then DeliveredQuantity
      when ReservedQuantity != 0
        then ReservedQuantity
      else 0
    end
    UsedQuantity
    , ContributionValue
    , VAT
    , InvoiceReference
    , TermsOfDelivery
    , TermsOfPayment
    , OrgId
    , ArticleId
    , CustomerId
    , FYID || '-' || if (AccountNumber='0', null, AccountNumber) AccountId
    , CostCenterId
    , ProjectId
  from data_extract
)

select
  OrderNum
  , OrderId
  , OrderDate
  , DeliveryDate
  , OurReference
  , Currency
  , ArticleNumber
  , Description
  , OrderedQuantity
  , DeliveredQuantity
  , isVATIncluded
  , round(PriceBeforeDiscount, 2) PriceBeforeDiscount
  , Discount
  , DiscountType
  -- because of how Discount AMOUNT applies, it is easier to calculate this in a separate CTE
  -- for 0 SalesValue rows, PriceAfterDiscount should be calculated from scratch
  , case
    when DiscountType = 'Percent' then round(PriceBeforeDiscount
      - Discount * PriceBeforeDiscount / 100, 2)
    else round(SalesValue / nullif(UsedQuantity, 0), 2)
  end PriceAfterDiscount
  , round(SalesValue, 2) SalesValue
  , round(OrderedValue, 2) OrderedValue
  , ContributionValue
  , VAT
  , InvoiceReference
  , TermsOfDelivery
  , TermsOfPayment
  , OrgId
  , ArticleId
  , CustomerId
  , AccountId
  , CostCenterId
  , ProjectId
from data_pre_calc
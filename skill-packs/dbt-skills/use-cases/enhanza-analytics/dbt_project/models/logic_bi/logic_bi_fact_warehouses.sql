{{ config(alias=(model_alias(model.name)), enabled = any_source_enabled(['fortnox'])) }}

with stockbalance as (
  select
    ArticleIdERP ArticleId
    , DataSource
    , DefaultCurrency
    , (select last_day(max(Date)) from {{ ref('erp_bi_fact_stockbalance') }}) TransactionDate
    , round(sum(QuantityInStock), 2) CurrentQty
    , sum(PurchasePrice * QuantityInStock) CurrentValue
    , avg(PurchasePrice) CurrentPrice
  from {{ ref('erp_bi_dim_articles') }}
  where StockGoods = TRUE
  group by 1, 2, 3, 4
)

, purchase_orders as (
  select
    ArticleIdERP ArticleId
    , DataSource
    , DefaultCurrency
    , last_day(deliveryDate, month) TransactionDate
    , round(avg(price), 2) ReceivedPrice
  from {{ ref('erp_bi_fact_purchase_orders') }}
  where ArticleId is not null
  group by 1, 2, 3, 4
)

, incominggoods as (
  select
    ig.ArticleIdERP ArticleId
    , ig.DataSource
    , ig.DefaultCurrency
    , last_day(ig.date, month) TransactionDate
    , round(sum(coalesce(receivedQuantity, 0)), 2) ReceivedQty
    , sum(coalesce(pu.ReceivedPrice, sb.CurrentPrice) * coalesce(receivedQuantity, 0)) ReceivedValue
  from {{ ref('erp_bi_fact_incoming_goods') }} ig
  left join purchase_orders pu
    on pu.ArticleId = ig.ArticleIdERP
    and pu.TransactionDate = last_day(ig.date, month)
  left join stockbalance sb
    on sb.ArticleId = ig.ArticleIdERP
  where isVoided is false
  group by 1, 2, 3, 4
)

, sales as (
  select
    ir.ArticleIdERP ArticleId
    , ir.DataSource
    , ir.DefaultCurrency
    , last_day(InvoiceDate) TransactionDate
    , round(sum(coalesce(DeliveredQuantity, 0)), 2) SoldQty
    , sum(SalesValue - ContributionValue) SoldValue
  from {{ ref('erp_bi_fact_invoice_rows') }} ir
  left join {{ ref('erp_bi_dim_articles') }} a
    on a.ArticleIdERP = ir.ArticleIdERP
  where a.StockGoods = TRUE
  group by 1, 2, 3, 4
)

, stocktakings as (
  select
    st.ArticleIdERP ArticleId
    , st.DataSource
    , st.DefaultCurrency
    , last_day(Date) TransactionDate
    , round(sum(coalesce(StockTakenQuantity,0)), 2) StockTakingQty
    , sum(sb.CurrentPrice * StockTakenQuantity) StockTakingValue
  from {{ ref('erp_bi_fact_stocktakings') }} st
  left join stockbalance sb
    on sb.ArticleId = st.ArticleIdERP
  group by 1, 2, 3, 4
)

, d0 as (select 
  coalesce(sb.TransactionDate, sl.TransactionDate, ig.TransactionDate, st.TransactionDate) TransactionDate
  , coalesce(sb.ArticleId, sl.ArticleId, ig.ArticleId, st.ArticleId) ArticleId
  , coalesce(sb.DataSource, sl.DataSource, ig.DataSource, st.DataSource) DataSource
  , coalesce(sb.DefaultCurrency, sl.DefaultCurrency, ig.DefaultCurrency, st.DefaultCurrency) DefaultCurrency
  , sb.CurrentQty
  , sb.CurrentValue
  , sl.SoldQty
  , sl.SoldValue
  , ig.ReceivedQty
  , ig.ReceivedValue
  , st.StockTakingQty
  , st.StockTakingValue
  , round(coalesce(ig.ReceivedQty,0) - coalesce(sl.SoldQty,0) - coalesce(st.StockTakingQty,0), 2) TotalPeriodChangeQty
  , round(coalesce(ig.ReceivedValue,0) - coalesce(sl.SoldValue,0) - coalesce(st.StockTakingValue,0), 2) TotalPeriodChangeValue
from stockbalance sb
full outer join sales sl
  on sl.ArticleId = sb.ArticleId
  and sl.TransactionDate = sb.TransactionDate
full outer join incominggoods ig
  on ig.ArticleId = coalesce(sb.ArticleId, sl.ArticleId)
  and ig.TransactionDate = coalesce(sb.TransactionDate, sl.TransactionDate)
full outer join stocktakings st
  on st.ArticleId = coalesce(sb.ArticleId, sl.ArticleId, ig.ArticleId)
  and st.TransactionDate = coalesce(sb.TransactionDate, sl.TransactionDate, ig.TransactionDate)
)

select
  TransactionDate
  , ArticleId
  , case
    when CurrentQty is not null then CurrentQty
    else round(ifnull(first_value(CurrentQty) over (partition by ArticleId order by TransactionDate desc), 0) -
  sum(TotalPeriodChangeQty) over (partition by ArticleId order by TransactionDate desc), 2)
  end OpeningQty
  , coalesce(SoldQty, 0) SoldQty
  , coalesce(ReceivedQty, 0) ReceivedQty
  , coalesce(StockTakingQty, 0) StockTakingQty
  , coalesce(TotalPeriodChangeQty, 0) TotalPeriodChangeQty
  , case
    when CurrentQty is not null then CurrentQty
    else round(ifnull(first_value(CurrentQty) over (partition by ArticleId order by TransactionDate desc), 0) -
  sum(TotalPeriodChangeQty) over (partition by ArticleId order by TransactionDate desc) + TotalPeriodChangeQty, 2)
  end ClosingQty
  , case
    when CurrentValue is not null then CurrentValue
    else round(ifnull(first_value(CurrentValue) over (partition by ArticleId order by TransactionDate desc), 0) -
  sum(TotalPeriodChangeValue) over (partition by ArticleId order by TransactionDate desc), 2)
  end OpeningValue
  , coalesce(SoldValue, 0) SoldValue
  , coalesce(ReceivedValue, 0) ReceivedValue
  , coalesce(StockTakingValue, 0) StockTakingValue
  , coalesce(TotalPeriodChangeValue, 0) TotalPeriodChangeValue
  , case
    when CurrentValue is not null then CurrentValue
    else round(ifnull(first_value(CurrentValue) over (partition by ArticleId order by TransactionDate desc), 0) -
  sum(TotalPeriodChangeValue) over (partition by ArticleId order by TransactionDate desc) + TotalPeriodChangeValue, 2)
  end ClosingValue
  , split(ArticleId, '-')[offset(0)] || '-' || REGEXP_EXTRACT(ArticleId, r'-([^\\-]+)$') OrgId 
  , DataSource
  , DefaultCurrency
from d0
order by 1 desc, 2
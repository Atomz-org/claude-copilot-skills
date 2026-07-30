{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

select
  a.*
except(ArticleId, QuantityInStock, ReservedQuantity, StockValue),
  s.StockPointCode as StockPointCode,
  sp.Name as StockPointName,
  ifnull(s.Instock,0) as Instock,
  ifnull(s.AvailableStock,0) as AvailableStock
from
  {{ ref('fortnox_bi_fact_stockbalance_staging') }} s
  full outer join {{ ref('fortnox_bi_dim_articles_staging') }} a on s.ArticleId = a.ArticleId
  left join {{ ref('fortnox_bi_dim_stockpoints_staging') }} sp on s.StockPointId = sp.StockPointId
where
a.StockGoods is true
-- and a.Active is true
--and DefaultStockLocation != StockPlace
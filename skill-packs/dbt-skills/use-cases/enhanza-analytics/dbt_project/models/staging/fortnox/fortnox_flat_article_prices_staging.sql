{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

select
  a.OrgId,
  c.OrgName,
  a.ArticleNumber,
  a.Description,
  a.SupplierName as Supplier,
  a.Active,
  a.Note,
  a.PurchasePrice,
  a.SalesPrice,
  a.DirectCost,
  sp.Description as Pricelist,
  p.FromQuantity,
  p.Price,
  sp.Comments,
  sp.Preselected as PreselectedPricelist
from
  {{ ref('fortnox_bi_dim_prices_staging') }} p full
  outer join {{ ref('fortnox_bi_dim_articles_staging') }} a on p.ArticleId = a.ArticleId
  left join {{ ref('fortnox_bi_dim_pricelists_staging') }} sp on p.PriceListId = sp.PriceListId
  left join {{ ref('fortnox_bi_dim_company_staging') }} c on a.OrgId = c.OrgId
-- where
--   a.StockGoods is true
  -- and a.Active is true
  --and DefaultStockLocation != StockPlace
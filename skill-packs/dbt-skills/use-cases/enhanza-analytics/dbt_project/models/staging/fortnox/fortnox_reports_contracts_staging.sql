{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}


with num_array as (
  Select
    distinct Rank as Ranking
  from
    Unnest(Generate_array(0, 48)) Rank
),
/*week_array as (
  Select
    distinct Dt as Date
  from
    Unnest(
      Generate_date_array('2020-01-01', '2020-01-01')
    ) Dt
),*/
current_data_continuous as (
  Select
    *
  from
    {{ ref('fortnox_bi_fact_contract_rows_staging') }}
  where
    Continuous is true
    and Status = "ACTIVE"
),
continuous_contracts as (
  Select
    A.*
  except(SalesValue),
    date_add(ContractDate, interval Ranking month) as ForcastedDate,
    SalesValue / InvoiceInterval as ForcastedSalesValue
  from
    Current_data_Continuous A
    cross join num_array B
),
Current_data_false as (
  Select
    *
  from
    {{ ref('fortnox_bi_fact_contract_rows_staging') }}
  where
    Continuous is false
    and Status = "ACTIVE"
),
fix_period_contract as (
  Select
    A.*
  except(SalesValue),
    date_add(ContractDate, interval Ranking month) as ForcastedDate,
    SalesValue / InvoiceInterval as ForcastedSalesValue
  from
    Current_data_false A
    inner join num_array B on Ranking <= ContractLength
  order by
    ForcastedDate
),
final as (
  Select
    *
  from
    Continuous_contracts
  union all
  Select
    *
  from
    fix_period_contract
)
select
  f.OrgId,
  cs.OrgName,
  c.Name as CustomerName,
  c.CustomerNumber,
  f.DocumentNumber,
  a.ArticleNumber as ArticleNumber,
  a.Description as ArticleName,
  f.OurReference,
  f.DeliveredQuantity,
  f.ContributionValue,
  f.ContractDate,
  f.Continuous,
  f.ContractLength,
  f.InvoiceInterval,
  f.PeriodEnd,
  f.PeriodStart,
  f.ForcastedDate,
  f.ForcastedSalesValue,
  f.Currency,
  cc.Description as CostCenter,
  p.Description as Project
from
  final f
  left join {{ ref('fortnox_bi_dim_company_staging') }} cs ON f.OrgId = cs.OrgId
  left join {{ ref('fortnox_bi_dim_customers_staging') }} c on f.CustomerId = c.CustomerId
  left join {{ ref('fortnox_bi_dim_articles_staging') }} a on f.ArticleId = a.ArticleId
  left join {{ ref('fortnox_bi_dim_cost_centers_staging') }} cc on f.CostCenterId = cc.CostCenterId
  left join {{ ref('fortnox_bi_dim_projects_staging') }} p on f.ProjectId = p.ProjectId
where
  ForcastedDate >= date_sub(current_date(), interval 13 month)
{{ config(
    alias=(model_alias(model.name)),
    enabled = any_source_enabled(['fortnox', 'seventime', 'tripletex', 'upsales', 'visma_eaccounting', 'visma_economic', 'xledger'])
) }}

select
  FinancialYearIdERP FinancialYearId
  , cast(FromDate as string) || " -> " || cast(ToDate as string) FyDates
  , FyCounter
  , DataSource
from {{ ref('erp_bi_dim_financial_years') }}
order by 1
{{ config(
    alias=(model_alias(model.name)),
    enabled = any_source_enabled(['fortnox', 'visma_eaccounting', 'visma_economic', 'tripletex'])
) }}

{% set cxm_cols = ['AccountId', 'ChartOfAccounts'] %}

with raw_data as (
    select
        AccountIdERP AccountId
        , split(AccountId, '-')[offset(0)] || '-' || Number AccountIdForGrouping
        , Number AccountNumber
        , AccountName
        , '(' || Number || ') ' || AccountName Account
        , format_date("%b'%y", fy.FromDate) || ' -> ' || format_date("%b'%y", fy.ToDate) FinancialYear
        , row_number() over (partition by split(AccountId, '-')[offset(0)] || '-' || Number order by fy.ToDate desc) rn
        , cxmLVL.CategoryId || '|' || cxmLVL.Level2ID AccountCategoryBreakdownID
        , d0.DataSource
        {{ cxm_select(cxm_cols) }}
    from {{ ref('erp_bi_dim_accounts') }} d0
    left join {{ ref('erp_bi_dim_financial_years') }} fy
        on fy.FinancialYearId = left(d0.AccountId, length(d0.AccountId)-5)
        and fy.DataSource = d0.DataSource
    {{ cxm_left_join(model_alias("dim_accounts"), cxm_cols) }}
)

, names as (
    select
        AccountIdForGrouping
        , AccountName AccountNameLatest
    from raw_data
    where rn=1
)

select
    raw_data.* except(rn)
    , names.AccountNameLatest
from raw_data
left join names
    on names.AccountIdForGrouping = raw_data.AccountIdForGrouping

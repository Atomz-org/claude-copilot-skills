{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  Number
  , AccountName
  , BalanceBroughtForward
  , BalanceCarriedForward
  , CostCenterId
  , AccountClassId
  , AccountClass
  , MainAccountId
  , MainAccount
  , SubAccountId
  , SubAccount
  , AccountId
  , FinancialYearId
from {{ ref('tripletex_bi_dim_accounts_staging') }}
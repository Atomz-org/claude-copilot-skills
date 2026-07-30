{{ config(alias=(model_alias(model.name))) }}
select 
  '1111111111' OrgId
  , Active
  , 0.0 BalanceBroughtForward
  , 0.0 BalanceCarriedForward
  , cast(null as string) CostCenter
  , CostCenterSettings
  , coalesce(bas.AccountName, a.Description) Description
  , Number
  , cast(null as string) `Project`
  , ProjectSettings
  , 0 SRU
  , cast(null as string) VATCode
  , Year
  , current_timestamp() ENZ_CREATED_AT
  , cast(null as timestamp) ENZ_MODIFIED_AT
  , current_timestamp() ENZ_SYNC_TS
  , 'Success' ENZ_DEBUG_INFO  
from {{ source('fortnox_api_demo', 'accounts') }} a
left join {{ source('public', 'bas_account_chart') }} bas
  on bas.Account = a.Number
where OrgId = (select min(OrgId) from {{ source('fortnox_api_demo', 'accounts') }})
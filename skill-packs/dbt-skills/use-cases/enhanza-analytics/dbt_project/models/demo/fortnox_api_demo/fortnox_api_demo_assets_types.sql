{{ config(alias = (model_alias(model.name))) }}

select
  Id
  , Type
  , {{blank_to_null('AccountAsset')}} AccountAsset
  , {{blank_to_null('AccountDepreciation')}} AccountDepreciation
  , {{blank_to_null('AccountRevaluation')}} AccountRevaluation
  , {{blank_to_null('AccountSaleLoss')}} AccountSaleLoss
  , {{blank_to_null('AccountSaleWin')}} AccountSaleWin
  , {{blank_to_null('AccountValueLoss')}} AccountValueLoss
  , {{blank_to_null('AccountWriteDown')}} AccountWriteDown
  , {{blank_to_null('AccountWriteDownAck')}} AccountWriteDownAck
  , Url
  , {{blank_to_null('Description')}} Description
  , InUse
  , {{blank_to_null('Notes')}} Notes
  , {{blank_to_null('Number')}} Number
  , OrgId
  , current_timestamp() ENZ_CREATED_AT
  , cast(null as timestamp) ENZ_MODIFIED_AT
  , current_timestamp() ENZ_SYNC_TS
  , 'Success' ENZ_DEBUG_INFO

from {{ source('fortnox_api_demo', 'assets_types') }}
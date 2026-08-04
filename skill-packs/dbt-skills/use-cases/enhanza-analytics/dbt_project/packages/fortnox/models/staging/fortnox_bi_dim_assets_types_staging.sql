{{ config(alias=model_alias(model.name), enabled = source_is_enabled(model.name)) }}

select
  OrgId || '-' || Id AssetTypeId
  , Type AssetType
  , {{blank_to_null('AccountAsset')}} AccountAsset
  , {{blank_to_null('AccountDepreciation')}} AccountDepreciation
  , {{blank_to_null('AccountRevaluation')}} AccountRevaluation
  , {{blank_to_null('AccountSaleLoss')}} AccountSaleLoss
  , {{blank_to_null('AccountSaleWin')}} AccountSaleWin
  , {{blank_to_null('AccountValueLoss')}} AccountValueLoss
  , {{blank_to_null('AccountWriteDown')}} AccountWriteDown
  , {{blank_to_null('AccountWriteDownAck')}} AccountWriteDownAck
  , Url AssetTypeUrl
  , {{blank_to_null('Description')}} Description
  , InUse InUse
  , {{blank_to_null('Notes')}} Notes
  , {{blank_to_null('Number')}} Number
  , OrgId
  /*, OrgId || '-' || AccountAssetId AccountAssetId
  , OrgId || '-' || AccountDepreciationId AccountDepreciationId
  , OrgId || '-' || AccountRevaluationId AccountRevaluationId
  , OrgId || '-' || AccountSaleLossId AccountSaleLossId
  , OrgId || '-' || AccountSaleWinId AccountSaleWinId
  , OrgId || '-' || AccountValueLossId AccountValueLossId
  , OrgId || '-' || AccountWriteDownId AccountWriteDownId
  , OrgId || '-' || AccountWriteDownAckId AccountWriteDownAckId */

from {{ source('fortnox_api', 'assets_types') }}
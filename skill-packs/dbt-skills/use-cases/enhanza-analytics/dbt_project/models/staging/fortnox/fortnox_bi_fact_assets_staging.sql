{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  OrgId || '-' || Id AssetId
  , Status
  , Type AssetType
  , OrgId || '-' || TypeId AssetTypeId
  , date(AcquisitionDate) AcquisitionDate
  , date(AcquisitionStart) AcquisitionStart
  , AcquisitionValue
  , DepreciateToResidualValue
  , {{blank_to_null('DepreciatedTo')}} DepreciatedTo
  , date(DepreciationFinal) DepreciationFinal
  , {{blank_to_null('InsuredNumber')}} InsuredNumber
  , {{blank_to_null('InsuredWith')}} InsuredWith
  , ManualOb
  , Url AssetUrl
  , {{blank_to_null('Brand')}} Brand
  , {{blank_to_null('Department')}} Department
  , {{blank_to_null('Room')}} Room
  , {{blank_to_null('Placement')}} Placement
  , {{blank_to_null('Description')}} `Description`
  , {{blank_to_null('Notes')}} Notes
  , {{blank_to_null('Reference')}} Reference
  , OrgId
  , OrgId || '-' || CostCenter CostCenterId
  , OrgId || '-' || `Project` ProjectId
from {{ source('fortnox_api', 'assets') }}
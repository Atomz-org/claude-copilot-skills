{{ config(materialized='ephemeral', enabled = var('is_seventime_enabled', false)) }}

with main as (
  select
    categoryName RegistrationCodeName
    , if(isWorkTime, 'WORK', if(isAbsence, 'ABSENCE', 'OTHERS')) RegistrationCodeType
    , user UserNo
    , date(timestamp) WorkedDate
    , time WorkedHours
    , invoiceableTime ChargeHours
    , timestamp_sub(endTimestamp, interval (cast(time*60 as int)) minute) StartTime
    , endTimestamp StopTime
    , t.description InvoiceText
    , {{ blank_to_null ('internalDescription') }} Note
    --CreatedBy, UpdatedBy, InvoiceBasisId not available
    , not(isInvoiceable) nonInvoiceable
    -- ChildId not available
    , t.createDate CreatedTime
    , cost UnitCost
    , pricePerHour UnitPrice
    --DocumentType not available
    , t._id ID
    , t.OrgId
    , null as CostCenterId
    , t.OrgId || '-' || t.customer CustomerId
    , t.OrgId || '-' || project ProjectId
    , t.OrgId || '-' || JSON_EXTRACT_SCALAR(invoiceRows, '$[0]._id') ArticleId
    , t.OrgId || '-' || user UserId
    , t.OrgId || '-' || workOrder WorkOrderId
    , userName UserName
  from {{ source('seventime_api', 'timelogs') }} t
  left join {{ source('seventime_api', 'workorders') }} wo
    on wo.OrgId=t.OrgId
    and wo._id=t.workOrder
)
select
  cast(RegistrationCodeType as STRING) as RegistrationCodeType
  , cast(null as STRING) as RegistrationCodeId
  , cast(RegistrationCodeName as STRING) as RegistrationCodeName
  , cast(nonInvoiceable as BOOL) as nonInvoiceable
  , cast(UserNo as STRING) as UserNo
  , cast(UserId as STRING) as UserId
  , cast(UserName as STRING) as UserName
  , cast(WorkedDate as DATE) as WorkedDate
  , cast(StartTime as TIMESTAMP) as StartTime
  , cast(StopTime as TIMESTAMP) as StopTime
  , cast(WorkedHours as FLOAT64) as WorkedHours
  , cast(ChargeHours as FLOAT64) as ChargeHours
  , cast(UnitCost as FLOAT64) as UnitCost
  , cast(UnitPrice as FLOAT64) as UnitPrice
  , cast(ID as STRING) as DocumentId
  , cast(null as STRING) as DocumentType
  , cast(null as STRING) as IssueCategory1
  , {{ add_erp_fields(columns=['ArticleId', 'CostCenterId', 'CustomerId', 'OrgId', 'ProjectId', 'UserId']) }}
from main
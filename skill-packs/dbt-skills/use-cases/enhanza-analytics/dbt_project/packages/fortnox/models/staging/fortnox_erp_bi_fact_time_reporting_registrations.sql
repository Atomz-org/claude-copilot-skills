{{ config(materialized='ephemeral', enabled = var('is_fortnox_enabled', false)) }}

select
    cast(RegistrationCodeType as STRING) as RegistrationCodeType,
    cast(RegistrationCodeId as STRING) as RegistrationCodeId,
    cast(RegistrationCodeName as STRING) as RegistrationCodeName,
    cast(nonInvoiceable as BOOL) as nonInvoiceable,
    cast(UserNo as STRING) as UserNo,
    cast(UserId as STRING) as UserId,
    cast(null as STRING) as UserName,
    cast(WorkedDate as DATE) as WorkedDate,
    cast(StartTime as TIMESTAMP) as StartTime,
    cast(StopTime as TIMESTAMP) as StopTime,
    cast(WorkedHours as FLOAT64) as WorkedHours,
    cast(ChargeHours as FLOAT64) as ChargeHours,
    cast(UnitCost as FLOAT64) as UnitCost,
    cast(UnitPrice as FLOAT64) as UnitPrice,
    cast(DocumentId as STRING) as DocumentId,
    cast(DocumentType as STRING) as DocumentType,
    cast(null as STRING) as IssueCategory1,
{{ add_erp_fields(columns=['ArticleId', 'CostCenterId', 'CustomerId', 'OrgId', 'ProjectId', 'UserId']) }}
from {{ ref('fortnox_bi_time_reporting_registrations_staging') }}
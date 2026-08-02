{{ config(materialized='ephemeral', enabled = var('is_tempo_enabled', false)) }}

select
    cast(RegisteredType as STRING) as RegistrationCodeType,
    cast(null as STRING) as RegistrationCodeId,
    cast(null as STRING) as RegistrationCodeName,
    cast(IsInvoicable as BOOL) as nonInvoiceable,
    cast(UserNo as STRING) as UserNo,
    cast(UserId as STRING) as UserId,
    cast(null as STRING) as UserName,
    cast(RegisteredDate as DATE) as WorkedDate,
    cast(StartTime as TIMESTAMP) as StartTime,
    cast(EndTime as TIMESTAMP) as StopTime,
    cast(WorkedHours as FLOAT64) as WorkedHours,
    cast(ChargeHours as FLOAT64) as ChargeHours,
    cast(UnitCost as FLOAT64) as UnitCost,
    cast(UnitPrice as FLOAT64) as UnitPrice,
    cast(DocumentNo as STRING) as DocumentId,
    cast(DocumentType as STRING) as DocumentType,
    cast(IssueCategory1 as STRING) as IssueCategory1,
{{ add_erp_fields(columns=['ArticleId', 'CostCenterId', 'CustomerId', 'OrgId', 'ProjectId', 'UserId']) }}
from {{ ref('tempo_bi_fact_time_reporting_registrations_staging') }}
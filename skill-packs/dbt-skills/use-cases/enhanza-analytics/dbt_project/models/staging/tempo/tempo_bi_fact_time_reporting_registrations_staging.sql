{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
    w.org_id || '-' || {{ blank_to_null('cast(w.issue.id as string)') }} as ArticleId
    , null as CostCenterId
    , null as CustomerId
    , 'tempo' as DataSource
    , null as DocumentNo
    , null as DocumentType
    , TIMESTAMP_ADD(w.startDateTimeUTC, interval w.timeSpentSeconds second) as EndTime
    , null as IsInvoicable
    , w.org_id as OrgId
    , null as ProjectId
    , date(w.createdAt) as RegisteredDate
    , null as RegisteredSubType
    , 'work' as RegisteredType
    , w.startDateTimeUTC as StartTime
    , null as UnitCost
    , null as UnitPrice
    , w.org_id || '-' || w.author.accountId as UserId
    , w.author.accountId as UserNo
    , null as UserGroup
    , null as UserSubGroup
    , (select val.value from UNNEST(w.attributes.values) as val LIMIT 1) as IssueCategory1
    , w.timeSpentSeconds / 3600.0 as WorkedHours
    , null as ChargeHours
    , null as DefaultCurrency
from
    {{ source('tempo_api', 'worklogs') }} w
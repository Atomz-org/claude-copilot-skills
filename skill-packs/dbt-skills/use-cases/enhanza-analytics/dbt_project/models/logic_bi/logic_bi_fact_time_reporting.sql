{{ config(
    alias=(model_alias(model.name)),
    enabled=any_source_enabled(['fortnox', 'seventime', 'tempo'])
) }}

-- depends_on: {{ ref('erp_bi_dim_employees') }}
-- depends_on: {{ ref('categories_x_mapping') }}

{% set trr_query %}
with ids as (
    select distinct
        UserId,
        max(CostCenterIdERP) CostCenterId,
        max(ProjectIdERP) ProjectId
    from {{ ref('erp_bi_fact_time_reporting_registrations') }}
    group by all
)

select
    initcap(d0.RegistrationCodeType) RegisteredType,
    replace(coalesce(cc.Description, d0.RegistrationCodeName, 'N/A, ' || d0.RegistrationCodeId), '\u2013', '-') RegisteredSubType,
    not d0.nonInvoiceable isInvoicable,
    case
    when {{ blank_to_null('d0.UserName') }} is not null
    then d0.UserName
    else d0.UserIdERP
    end as UserId,
    cxm.Level1 UserGroup,
    cxm.Level2 UserSubGroup,
    d0.WorkedDate RegisteredDate,
    d0.StartTime,
    d0.StopTime EndTime,
    d0.WorkedHours,
    d0.ChargeHours,
    d0.UnitCost,
    d0.UnitPrice,
    d0.OrgIdERP OrgId,
    ids.CostCenterId,
    ids.ProjectId,
    d0.CustomerIdERP || '-C' CustomerId,
    d0.ArticleIdERP ArticleId,
    regexp_extract(d0.DocumentId, r'^[^\-]+-(.*)') DocumentNo,
    d0.DocumentType,
    d0.IssueCategory1,
    d0.DataSource,
    d0.DefaultCurrency
from {{ ref('erp_bi_fact_time_reporting_registrations') }} d0
left join {{ source('public', 'cause_codes') }} cc
    on cc.Code = d0.RegistrationCodeId
    and d0.DataSource = 'Fortnox'
left join ids
    on ids.UserId = d0.UserId
left join {{ ref('erp_bi_dim_employees') }} empl
    on empl.EmployeeName = d0.UserName
    and split(empl.EmployeeId, '-')[offset(0)] = cast(d0.OrgIdERP as string)
left join {{ ref('categories_x_mapping') }} cxm
    on cxm.DimensionIdERP = d0.OrgIdERP || '|' || coalesce(d0.UserName, {{ blank_to_null('d0.UserNo') }})
    and cxm.DimensionTable='dim_employees'
    and cxm.DimensionColumn='EmployeeId'
order by d0.WorkedDate desc
{% endset %}

{%- set all_queries = [trr_query] -%}

{{ union_queries(all_queries) }}
{{ config(alias=(model_alias(model.name))) }}
select
    '1111111111' OrgId
    , Id
    , {{ demo_date('FromDate') }} FromDate
    , {{ demo_date('ToDate') }} ToDate
    , 'BAS' AccountChartType
    , 'ACCRUAL' AccountingMethod
    , current_timestamp() ENZ_CREATED_AT
    , cast(null as timestamp) ENZ_MODIFIED_AT
    , current_timestamp() ENZ_SYNC_TS
    , 'Success' ENZ_DEBUG_INFO 
from {{ source('fortnox_api_demo', 'financial_years') }} 
where OrgId= (select min(OrgId) from {{ source('fortnox_api_demo', 'financial_years') }})
and extract(year from FromDate) in ( 
    {{ global_configs('demo_max_year') }}
    , {{ global_configs('demo_max_year') }} - 1 
)
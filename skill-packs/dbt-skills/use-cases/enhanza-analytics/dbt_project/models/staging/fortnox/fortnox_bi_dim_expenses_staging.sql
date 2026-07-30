{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select 
OrgId || '-' || Code ExpenseId
, Code ExpenseCode
, Text Description
from {{ source('fortnox_api', 'expenses') }}
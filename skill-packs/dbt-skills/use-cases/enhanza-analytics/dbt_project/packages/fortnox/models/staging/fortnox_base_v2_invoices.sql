{{ config(
    alias='base_v2_invoices',
    enabled=var('is_fortnox_enabled', 'False') | as_bool,
    materialized='ephemeral'
) }}

select *
from {{ source('fortnox_api', 'v2_invoices') }}
where 1=1
  {{ fortnox_start_year_filter('OrgId', 'InvoiceDate') }}


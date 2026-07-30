--Purpose: DEMO workspace is based on Enhanza's workspace. 
--For those endpoints that are not available in Enhanza Fortnox, we create blank tables to mimic the structure
--Usage: in DEMO datasets only, for tables outside of Enhanza's Fortnox scope

{%- macro demo_blank_table() -%}
  {{ config(alias=(model_alias(model.name))) }}
  select 
    * 
  from {{ source('fortnox_api_demo', model_alias(model.name)) }}
  where FALSE
{%- endmacro -%}
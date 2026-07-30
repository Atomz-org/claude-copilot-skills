{{ config(materialized='ephemeral') }}

{{ erp_union('dim_articles') }}

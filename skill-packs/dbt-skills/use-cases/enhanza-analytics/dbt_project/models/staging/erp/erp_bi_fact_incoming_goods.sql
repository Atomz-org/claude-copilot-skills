{{ config(materialized='ephemeral') }}

{{ erp_union('fact_incoming_goods') }}

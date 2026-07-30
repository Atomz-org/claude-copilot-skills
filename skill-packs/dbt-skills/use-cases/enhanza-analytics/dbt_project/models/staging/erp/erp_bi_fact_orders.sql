{{ config(materialized='ephemeral') }}

{%- set cfg = {} -%}

{% if var('is_fortnox_enabled', false) %}
    {%- do cfg.update({
        'fortnox': {'query_ref': ref('fortnox_erp_bi_fact_orders')}
    }) -%}
{% endif %}

{% if var('is_upsales_enabled', false) %}
    {%- do cfg.update({
        'upsales': {'query_ref': ref('upsales_erp_bi_fact_orders')}
    }) -%}
{% endif %}

{% if var('is_visma_economic_enabled', false) %}
    {%- do cfg.update({
        'visma_economic': {'query_ref': ref('visma_economic_erp_bi_fact_orders')}
    }) -%}
{% endif %}

{{ configure_erp(cfg) }}
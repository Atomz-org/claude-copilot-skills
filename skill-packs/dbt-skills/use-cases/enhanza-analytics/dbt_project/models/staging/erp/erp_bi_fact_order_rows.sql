{{ config(materialized='ephemeral') }}

{%- set cfg = {} -%}

{% if var('is_fortnox_enabled', false) %}
    {%- do cfg.update({
        'fortnox': {'query_ref': ref('fortnox_erp_bi_fact_order_rows')}
    }) -%}
{% endif %}

{% if var('is_upsales_enabled', false) %}
    {%- do cfg.update({
        'upsales': {'query_ref': ref('upsales_erp_bi_fact_order_rows')}
    }) -%}
{% endif %}

{% if var('is_favrit_enabled', false) %}
    {%- do cfg.update({
        'favrit': {'query_ref': ref('favrit_erp_bi_fact_order_rows')}
    }) -%}
{% endif %}

{{ configure_erp(cfg) }}
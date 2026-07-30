{{ config(materialized='ephemeral') }}

{%- set cfg = {} -%}

{% if var('is_fortnox_enabled', false) %}
    {%- do cfg.update({
        'fortnox': {'query_ref': ref('fortnox_erp_bi_fact_offers')}
    }) -%}
{% endif %}

{% if var('is_seventime_enabled', false) %}
    {%- do cfg.update({
        'seventime': {'query_ref': ref('seventime_erp_bi_fact_offers')}
    }) -%}
{% endif %}

{{ configure_erp(cfg) }}
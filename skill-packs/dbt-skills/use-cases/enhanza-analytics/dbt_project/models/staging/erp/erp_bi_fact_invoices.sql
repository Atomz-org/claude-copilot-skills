{{ config(materialized='ephemeral') }}

{%- set cfg = {} -%}

{% if var('is_fortnox_enabled', false) %}
    {%- do cfg.update({
        'fortnox': {'query_ref': ref('fortnox_erp_bi_fact_invoices')}
    }) -%}
{% endif %}

{% if var('is_seventime_enabled', false) %}
    {%- do cfg.update({
        'seventime': {'query_ref': ref('seventime_erp_bi_fact_invoices')}
    }) -%}
{% endif %}

{% if var('is_tripletex_enabled', false) %}
    {%- do cfg.update({
        'tripletex': {'query_ref': ref('tripletex_erp_bi_fact_invoices')}
    }) -%}
{% endif %}

{% if var('is_visma_eaccounting_enabled', false) %}
    {%- do cfg.update({
        'visma_eaccounting': {'query_ref': ref('visma_eaccounting_erp_bi_fact_invoices')}
    }) -%}
{% endif %}

{% if var('is_visma_economic_enabled', false) %}
    {%- do cfg.update({
        'visma_economic': {'query_ref': ref('visma_economic_erp_bi_fact_invoices')}
    }) -%}
{% endif %}

{{ configure_erp(cfg) }}
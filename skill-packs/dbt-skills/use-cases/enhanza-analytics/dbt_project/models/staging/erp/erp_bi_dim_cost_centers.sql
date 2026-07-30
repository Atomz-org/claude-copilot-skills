{{ config(materialized='ephemeral') }}

{%- set cfg = {} -%}

{% if var('is_fortnox_enabled', false) %}
    {%- do cfg.update({
        'fortnox': {'query_ref': ref('fortnox_erp_bi_dim_cost_centers')}
    }) -%}
{% endif %}

{% if var('is_tripletex_enabled', false) %}
    {%- do cfg.update({
        'tripletex': {'query_ref': ref('tripletex_erp_bi_dim_cost_centers')}
    }) -%}
{% endif %}

{% if var('is_visma_eaccounting_enabled', false) %}
    {%- do cfg.update({
        'visma_eaccounting': {'query_ref': ref('visma_eaccounting_erp_bi_dim_cost_centers')}
    }) -%}
{% endif %}

{% if var('is_xledger_enabled', false) %}
    {%- do cfg.update({
        'xledger': {'query_ref': ref('xledger_erp_bi_dim_cost_centers')}
    }) -%}
{% endif %}

{{ configure_erp(cfg) }}
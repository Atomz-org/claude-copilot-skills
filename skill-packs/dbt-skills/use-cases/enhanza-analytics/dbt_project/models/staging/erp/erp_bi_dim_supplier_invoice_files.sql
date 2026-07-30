{{ config(materialized='ephemeral') }}

{%- set cfg = {} -%}

{% if var('is_fortnox_enabled', false) %}
    {%- do cfg.update({
        'fortnox': {'query_ref': ref('fortnox_erp_bi_dim_supplier_invoice_files')}
    }) -%}
{% endif %}

{{ configure_erp(cfg) }}
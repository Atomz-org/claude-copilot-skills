{{ config(alias=model_alias(model.name), enabled = var('is_fortnox_enabled', false)) }}

{%- set cfg = {} -%}

{% if var('is_fortnox_enabled', false) %}
    {%- do cfg.update({
        'fortnox': {'query_ref': ref('fortnox_erp_bi_dim_stockpoints')}
    }) -%}
{% endif %}

{{ configure_erp(cfg) }}

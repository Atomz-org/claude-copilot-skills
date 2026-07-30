{{ config(materialized='ephemeral') }}

{%- set cfg = {} -%}

{% if var('is_fortnox_enabled', false) %}
    {%- do cfg.update({
        'fortnox': {'query_ref': ref('fortnox_erp_bi_fact_time_reporting_registrations')}
    }) -%}
{% endif %}

{% if var('is_seventime_enabled', false) %}
    {%- do cfg.update({
        'seventime': {'query_ref': ref('seventime_erp_bi_fact_time_reporting_registrations')}
    }) -%}
{% endif %}

{% if var('is_tempo_enabled', false) %}
    {%- do cfg.update({
        'tempo': {'query_ref': ref('tempo_erp_bi_fact_time_reporting_registrations')}
    }) -%}
{% endif %}

{{ configure_erp(cfg) }}
--Purpose: all user-facing views and tables are fetching * from staging, so config block is automated
--Usage: 
    --alias is defined based on model name
    --enabled is typically based on folder/model name, and only for erp and logic defined per endpoint
    --clustering is optional and is needed only for logic_bi.fact tables

{%- macro auto_config(suffix='_staging', cluster_by=None) -%}
    {%- set model_name = model.name -%}

    {# Check if model name starts with any prefix in special_enabled list #}
    {%- set result_enabled = [] -%}
    {%- set define_enabled = false -%}
    {%- for prefix in global_configs('special_enabled_prefixes') -%}
        {%- if model_name.startswith(prefix) -%}
            {{ result_enabled.append("TRUE") or "" }}
        {%- endif -%}
    {%- endfor -%}
    {%- if "TRUE" in result_enabled -%}
        {%- set define_enabled = True -%}
    {%- endif -%}

    {%- set enabled_value = source_is_enabled(model_name) | as_bool if define_enabled else none -%}

    {%- if enabled_value is not none and cluster_by is not none -%}
        {{ config(
            alias = model_alias(model_name),
            enabled = enabled_value,
            cluster_by = cluster_by
        ) }}
    {%- elif enabled_value is not none -%}
        {{ config(
            alias = model_alias(model_name),
            enabled = enabled_value
        ) }}
    {%- elif cluster_by is not none -%}
        {{ config(
            alias = model_alias(model_name),
            cluster_by = cluster_by
        ) }}
    {%- else -%}
        {{ config(
            alias = model_alias(model_name)
        ) }}
    {%- endif -%}

    select * from {{ ref(model_name + suffix) }}
{%- endmacro -%}
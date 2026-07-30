{% macro configure_erp(cfg) %}
    {%- set all_sources = global_configs('all_available_sources') -%}
    {%- set ns = namespace(queries=[]) -%}
    {%- for source_name, erp_source_cfg in cfg.items() -%}
        {%- set source_cfg = all_sources[source_name] -%}
        {%- if not source_cfg.enabled -%}
          {%- continue -%}
        {%- endif -%}
        {%- do ns.queries.append("select * from "~erp_source_cfg['query_ref']) -%}
    {%- endfor -%}
    {{ union_queries(ns.queries) }}
{% endmacro %}
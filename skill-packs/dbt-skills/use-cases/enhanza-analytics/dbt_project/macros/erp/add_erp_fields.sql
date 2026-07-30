{% macro add_erp_fields(columns) %}
  {#-
    Adds:
    - DefaultCurrency (from the matched enabled source)
    - DataSource as 'ds_<source_key>'
    - <Id>ERP alias for every column in `columns` ending with 'Id'
      except names from global_configs('id_erp_exceptions')
    If no source matches, DataSource is 'ds_unknown' and DefaultCurrency is NULL.
  -#}

  {%- set all_sources = global_configs('all_available_sources') -%}
  {%- set exceptions = global_configs('id_erp_exceptions') -%}  {# Used for filtering exceptions #}

  {%- set model_name = model.name -%}

  {# Initialize with defaults for an unmatched source #}
  {% set matched_source = namespace(name='unknown', default_currency=none) %}

  {%- for source_name, source_cfg in all_sources.items() -%}
    {# Check if source is enabled AND model name starts with source name #}
    {%- if source_cfg.enabled and model_name.startswith(source_name) -%}
      {%- set matched_source.name = source_name -%}
      {%- set matched_source.display_name = source_cfg.get('name', source_name) -%}
      {%- set matched_source.default_currency = source_cfg.get('default_currency') -%}
      {%- break -%}
    {%- endif -%}
  {%- endfor -%}

  {#- Output DataSource and DefaultCurrency fields -#}
  '{{ matched_source.display_name }}' as DataSource,
  {%- if matched_source.default_currency is not none -%}
    '{{ matched_source.default_currency }}' as DefaultCurrency
  {%- else -%}
    cast(null as string) as DefaultCurrency
  {%- endif %}

  {# Generate <Id>ERP aliases, filtering to include only 'Id'-ending columns that are not exceptions #}
  {%- for c in columns -%}
    {%- if c.endswith('Id') and c not in exceptions -%}
    , {{ c }} || '-ds_{{ matched_source.name}}' as {{ c }}ERP
    {%- endif -%}
  {%- endfor -%}
{% endmacro %}
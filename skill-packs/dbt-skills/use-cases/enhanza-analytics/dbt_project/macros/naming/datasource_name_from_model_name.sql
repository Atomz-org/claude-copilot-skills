--Purpose: returns datasource name i.e. fortnox from the full model name
--Usage: DRY principle

{%- macro datasource_name_from_model_name(table_name) -%}
    {%- set split_keywords = ['_bi_', '_demo_', '_api_', '_flat_', '_reports_'] -%}
    {%- for keyword in split_keywords -%}
        {%- if keyword in table_name -%}
            {{ return(table_name.split(keyword)[0]) }}
        {%- endif -%}
    {%- endfor -%}
    {{ return(table_name) }}
{%- endmacro -%}

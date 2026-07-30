{% macro scaffold_surrogate_key(column_name) -%}
    md5(cast({{ column_name }} as string))
{%- endmacro %}

{% macro scaffold_current_timestamp() -%}
    current_timestamp
{%- endmacro %}

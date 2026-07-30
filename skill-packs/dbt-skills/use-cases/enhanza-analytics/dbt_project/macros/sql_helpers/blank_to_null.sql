-- Purpose: Converts blank strings ('') in a column to NULL values in BigQuery.
-- Usage: Use this macro to ensure empty strings are treated as NULLs in your models.

{%- macro blank_to_null(column) -%}
    nullif({{ column }}, '')
{%- endmacro %}
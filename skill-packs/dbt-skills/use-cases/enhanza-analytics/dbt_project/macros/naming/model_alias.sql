--Purpose: define the endpoint name in BigQuery based on file name in DBT
--Usage: with 3 simple checks, return a "user-friendly" name of the model as alias

--See also: macro global_configs(naming_special_cases) for models with naming exceptions

{%- macro model_alias(table_name) -%}

    {# Step 0: Remove '_staging' suffix if present #}
    {%- set stripped_name = remove_staging_from_name(table_name) -%}

    {# Step 1: Check full-name exceptions from naming_special_cases dict #}
    {%- set naming_special_cases = global_configs('naming_special_cases') -%}
    {%- if naming_special_cases.get(table_name) is not none -%}
        {{ return(naming_special_cases[table_name]) }}
    {%- endif -%}

    {# Step 2: If name was changed by remove_staging_from_name, return it #}
    {%- if stripped_name != table_name -%}
        {{ return(stripped_name) }}
    {%- endif -%}

    {# Step 3: Apply known keyword-based patterns #}
    {%- set split_keywords = ['_bi_', '_demo_', '_api_', '_flat_', '_reports_'] -%}
    {%- for keyword in split_keywords -%}
        {%- if keyword in table_name -%}
            {{ return(table_name.split(keyword)[-1]) }}
        {%- endif -%}
    {%- endfor -%}

    {# Step 4: Fallback - use the name directly #}
    {{ return(table_name) }}
    
{%- endmacro -%}
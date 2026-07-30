--Purpose: removes "_staging" from the model name, reusable
--Usage: applying DRY principle

{%- macro remove_staging_from_name(model_name) -%}

    {%- if model_name.endswith('_staging') -%}
        {%- set model_name = model_name[:-8] -%}
    {%- endif -%}
    
    {{ return(model_name) }}

{%- endmacro -%}
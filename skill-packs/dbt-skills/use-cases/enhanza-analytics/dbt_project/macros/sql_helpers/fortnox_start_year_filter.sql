{% macro fortnox_start_year_filter(org_id_column='OrgId', date_column='InvoiceDate') %}

{%- set start_years_mapping = var('start_years', {}) -%}

{%- if start_years_mapping -%}
    {#- If mapping is provided, generate CASE WHEN conditions for each org -#}
    and (
    {%- for org_id, start_year_date in start_years_mapping.items() %}
        ({{ org_id_column }} = '{{ org_id }}' and date({{ date_column }}) >= date('{{ start_year_date }}'))
        {%- if not loop.last %} or {% endif %}
    {%- endfor %}
        or {{ org_id_column }} not in (
            {%- for org_id in start_years_mapping.keys() %}
            '{{ org_id }}'{% if not loop.last %}, {% endif %}
            {%- endfor %}
        )
    )
{%- endif -%}

{% endmacro %}


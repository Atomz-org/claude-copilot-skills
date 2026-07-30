{% macro cxm_left_join(table_name, key_columns) %}

    {%- if not key_columns or key_columns | length == 0 -%}
        {{ return('') }}
    {%- else -%}
        {%- set queries = [] -%}

        {# Loop over the passed key columns #}
        {%- for column in key_columns -%}
            {%- if column == 'ChartOfAccounts' -%}
                {%- set column = "AccountId" -%}
                {%- set join_name = "chart_of_accounts" -%}
                {%- set column_value = "split(d0." ~ column ~ ", '-')[offset(0)] || '-' || d0.Number " -%}
                {%- set query -%}
                left join {{ ref('categories_x_mapping') }} cxmLVL
                    on cxmLVL.DimensionTable = '{{ join_name }}'
                    and cxmLVL.DimensionColumn = '{{ column }}'
                    and cxmLVL.DimensionIdERP = {{ column_value }}
                {%- endset -%}
            {%- else -%}
                {%- if column == 'AccountId' -%}
                    {%- set column_value = "split(d0." ~ column ~ ", '-')[offset(0)] || '-' || d0.Number " -%}
                {%- elif column == 'EmployeeId' -%}
                    {%- set column_value = "split(d0.EmployeeIdERP, '-')[offset(0)] || '-' || REGEXP_EXTRACT(d0.EmployeeIdERP, r'^(?:[^-]*-){2}(.*)')  || '|' || d0.EmployeeName || ' (' || d0.EmployeeNumber || ')'" -%}
                {%- else -%}
                    {%- set column_value = "d0." ~ column ~ "ERP" if column.endswith('Id') else "d0." ~ column -%}
                {%- endif -%}

                {%- if column == 'City' -%}
                    {%- set join_name = "dim_customers_suppliers" -%}
                {%- else -%}
                    {%- set join_name = model_alias(table_name) -%}
                {%- endif -%}

                {%- set query -%}
                left join {{ ref('categories_x_mapping') }} cxm{{ loop.index }}
                    on cxm{{ loop.index }}.DimensionTable = '{{ join_name }}'
                    and cxm{{ loop.index }}.DimensionColumn = '{{ column }}'
                    and cxm{{ loop.index }}.DimensionIdERP = {{ column_value }}
                {%- endset -%}

            {%- endif -%}
            {%- do queries.append(query) -%}
        {%- endfor %}

        {# Combine all queries #}
        {{ union_queries(queries, ' ') }}
    {%- endif -%}
{% endmacro %}
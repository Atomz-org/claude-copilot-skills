-- Purpose: concatenate separate string SQLs into one using UNION ALL operator
-- Usage: heavily used in `erp_bi` and `logic_bi` to avoid redundant code lines

{%- macro union_queries(list_of_queries, join_by='\nUNION ALL\n') -%}
    {%- set filtered_queries = [] -%}

    {#- Filter out empty queries if any -#}
    {%- for query in list_of_queries -%}
        {%- if query|length > 1 -%}
            {{ filtered_queries.append(query) or "" }}
        {%- endif -%}
    {%- endfor -%}

    {%- set final_query = filtered_queries | join(join_by) -%}

    {{ final_query }}
{%- endmacro -%}
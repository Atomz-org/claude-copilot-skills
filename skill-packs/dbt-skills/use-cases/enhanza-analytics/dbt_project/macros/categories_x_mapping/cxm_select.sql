{% macro cxm_select(key_columns) %}

    {%- if not key_columns or key_columns | length == 0 -%}
        {{ return('') }}
    {%- else -%}
        {%- set queries = [] -%}

        {# Loop over the passed key columns #}
        {%- for column in key_columns -%}
            {%- set clean_column = column[:-2] if column.endswith('Id') else column -%}
            {%- set query -%}
            {%- if column == 'ChartOfAccounts' -%}
                , cxmLVL.Level1 AccountClass
                , cxmLVL.Level1ID AccountClassId
                , cxmLVL.Level2 AccountSubClass
                , cxmLVL.Level2ID AccountSubClassId
                , cxmLVL.Level3 AccountCategory
                , cxmLVL.CategoryId AccountCategoryId
            {%- else -%}
                , cxm{{ loop.index }}.Level1 {{ clean_column }}Group
                , cxm{{ loop.index }}.Level1ID {{ clean_column }}GroupId
                , cxm{{ loop.index }}.Level2 {{ clean_column }}SubGroup
                , cxm{{ loop.index }}.Level2ID {{ clean_column }}SubGroupId
                , cxm{{ loop.index }}.Level3 {{ clean_column }}SubSubGroup
                , cxm{{ loop.index }}.CategoryId {{ clean_column }}SubSubGroupId
            {%- endif -%}
            {%- endset -%}
            {%- do queries.append(query) -%}
        {%- endfor -%}

        {# Combine all queries #}
        {{ union_queries(queries, ' ') }}
    {%- endif -%}
{% endmacro %}
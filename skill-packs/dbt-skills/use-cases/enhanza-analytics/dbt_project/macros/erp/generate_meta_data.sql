--Purpose: automatically generates meta data for the data_source_BI dataset
--Usage: used in blank model in respective dataset

{% macro generate_meta_data() %}
    {% set model_name = model.name %}
    {{ config(alias=(model_alias(model_name)), enabled = source_is_enabled(model_name)) }}

    {% set datasource = datasource_name_from_model_name(model_name) %}
    {% set uid = var('uid') %}

    {% set dataset = datasource ~ "_api_" ~ uid %}
    
    {% set table_names_query %}
        SELECT table_name
        FROM `{{ dataset }}.INFORMATION_SCHEMA.TABLES`
        WHERE table_name != 'absence_causecodes'
    {% endset %}

    {% set results = run_query(table_names_query) %}

    {% if execute %}
        {% set table_names = results.columns[0].values() %}
    {% else %}
        {% set table_names = [] %}
    {% endif %}

    {% set queries = [] %}
    
    {% for table_name in table_names %}
        {% set query %}
            SELECT '{{ table_name }}' AS TableName, 
                   OrgId,  
                   MAX(ENZ_SYNC_TS) AS MaxSyncTs, 
                   COUNT(*) AS RowCount
            FROM `{{ dataset }}.{{ table_name }}`
            GROUP BY OrgId

            UNION ALL

            SELECT '{{ table_name }}' AS TableName, 
                   NULL AS OrgId, 
                   NULL AS MaxSyncTs, 
                   0 AS RowCount
            FROM (SELECT 1) AS dummy
            WHERE NOT EXISTS (SELECT 1 FROM `{{ dataset }}.{{ table_name }}`)
        {% endset %}
        {{ queries.append(query) or "" }}
    {% endfor %}

    {{ union_queries(queries) }}
{% endmacro %}
{#
    Purpose: Finds the single latest modification timestamp across all enabled API source datasets for a given tenant.
    Usage: This macro is called by the `latest_source_sync` view, which is used by Cube's refreshKey.
#}
{% macro get_latest_source_timestamp() %}
    {#- Get project-level variables from dbt_project.yml and environment variables -#}
    {% set uid = var('uid') %}
    {% set available_sources = var('available_sources') %}

    {#- Initialize an empty list to hold the SQL queries for each source -#}
    {% set max_ts_queries = [] %}

    {#- Loop through all potential source systems defined in dbt_project.yml -#}
    {% for source_name in available_sources %}
        {#- Check if the current source is enabled for this specific dbt run -#}
        {% if var('is_' ~ source_name ~ '_enabled', false) %}
            {#- Construct the full BigQuery dataset ID for the source -#}
            {% set dataset_id = source_name ~ '_api_' ~ uid %}

            {%- set query -%}
                SELECT MAX(TIMESTAMP_MILLIS(last_modified_time)) as latest_timestamp FROM `{{ dataset_id }}`.`__TABLES__`
            {%- endset -%}
            {#- Add the generated query to our list of queries -#}
            {{ max_ts_queries.append(query) or "" }}
        {% endif %}
    {% endfor %}

    {#- If any sources were enabled, combine their queries to find the overall max timestamp -#}
    {% if max_ts_queries | length > 0 %}
        SELECT MAX(latest_timestamp) AS latest_source_timestamp
        FROM (
            {{ union_queries(max_ts_queries) }}
        ) AS timestamps
    {% else %}
        {#- If no sources were enabled, return a single NULL row to ensure the view is still created correctly -#}
        SELECT CAST(NULL AS TIMESTAMP) as latest_source_timestamp
    {% endif %}
{% endmacro %}

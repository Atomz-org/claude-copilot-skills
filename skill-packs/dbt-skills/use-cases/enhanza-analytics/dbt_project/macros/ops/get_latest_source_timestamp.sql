{#
    Purpose: Finds the single latest modification timestamp across all enabled API source datasets for a given tenant.
    Usage: This macro is called by the `latest_source_sync` view, which is used by Cube's refreshKey.
#}
{% macro get_latest_source_timestamp() %}
    {#- Get project-level variables from dbt_project.yml and environment variables -#}
    {% set uid = var('uid') %}

    {#- The connector list comes from global_configs('all_available_sources') — the same
        registry erp_union(), model_is_provided(), and add_erp_fields() read. It used to
        come from a separate `available_sources` var, which meant onboarding a connector
        required remembering a second list; forget it and this view silently reports NULL
        forever, so Cube's refreshKey never fires.

        Setting `available_sources` explicitly still overrides the registry, for a run that
        needs to scope the freshness probe to a subset. -#}
    {% set override = var('available_sources', []) or [] %}
    {% set all_sources = global_configs('all_available_sources') %}
    {% set available_sources = override if override | length > 0 else all_sources.keys() | list %}

    {#- Initialize an empty list to hold the SQL queries for each source -#}
    {% set max_ts_queries = [] %}

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

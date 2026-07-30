{% macro cleanup_project(dry_run=True) %}

    {#
       Arguments:
       - dry_run: If True (default), logs commands. If False, executes DROP TABLE/VIEW.
    #}

    {% if not execute %}
        {{ return('') }}
    {% endif %}

    {% set current_uid = var('uid') %}
    {{ log("Starting Cleanup for UID: " ~ current_uid ~ "", info=True) }}

    {# 1. Build Expected State #}
    {% set active_schemas_config = {} %}

    {% for node in graph.nodes.values() | selectattr("resource_type", "in", ["model", "seed", "snapshot"]) %}
        {% set schema_name = node.schema | upper %}
        {% set table_name = node.alias | upper %}

        {% if schema_name not in active_schemas_config %}
            {% do active_schemas_config.update({schema_name: []}) %}
        {% endif %}

        {% do active_schemas_config[schema_name].append(table_name) %}
    {% endfor %}

    {# 2. Scan & Cleanup #}
    {{ log("Scanning active schemas for stale objects", info=True) }}

    {% for schema_upper, expected_tables in active_schemas_config.items() %}

        {% set get_real_name_query %}
            SELECT schema_name
            FROM {{ target.project }}.INFORMATION_SCHEMA.SCHEMATA
            WHERE UPPER(schema_name) = '{{ schema_upper }}'
            LIMIT 1
        {% endset %}

        {% set name_results = run_query(get_real_name_query) %}

        {% if name_results | length > 0 %}
            {# Extract the actual name, e.g., 'fortnox_bi_cgl...' (lowercase) #}
            {% set real_schema_name = name_results.columns[0].values()[0] %}
            {{ log("Verified schema exists: " ~ real_schema_name ~ ". Scanning for trash...", info=True) }}

            {% set get_tables_query %}
                SELECT table_name, table_type
                FROM `{{ target.project }}.{{ real_schema_name }}.INFORMATION_SCHEMA.TABLES`
            {% endset %}

            {% set existing_tables = run_query(get_tables_query) %}

            {% for row in existing_tables %}
                {% if row['table_name'] | upper not in expected_tables %}

                    {% set drop_type = 'VIEW' if row['table_type'] == 'VIEW' else 'TABLE' %}
                    {% set query = 'DROP ' ~ drop_type ~ ' IF EXISTS `' ~ target.project ~ '.' ~ real_schema_name ~ '.' ~ row["table_name"] ~ '`;' %}

                    {% if dry_run %}
                        {{ log("[DRY RUN] Would delete: " ~ real_schema_name ~ "." ~ row["table_name"], info=True) }}
                    {% else %}
                        {{ log("EXECUTING: " ~ query, info=True) }}
                        {% do run_query(query) %}
                    {% endif %}

                {% endif %}
            {% endfor %}
        {% else %}
             {{ log("Skipping schema " ~ schema_upper ~ " (does not exist in BQ)", info=True) }}
        {% endif %}
    {% endfor %}

    {{ log("Cleanup Finished", info=True) }}

{% endmacro %}
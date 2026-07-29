{#
    Cross-warehouse shims for the handful of expressions dbt Core does not already
    normalize. Prefer, in this order:

      1. plain ANSI SQL                       -- works everywhere, no macro needed
      2. dbt's own cross-database macros      -- {{ dbt.dateadd(...) }}, {{ dbt.type_numeric() }},
                                                 {{ dbt.safe_cast(...) }}, {{ dbt.datediff(...) }},
                                                 {{ dbt.concat(...) }}, {{ dbt.split_part(...) }}
      3. dbt_utils                            -- generate_surrogate_key, date_spine, star
      4. adapter.dispatch, below              -- only when 1-3 genuinely do not cover it

    Every macro here costs a reader one indirection. Three implementations of something
    ANSI already gives you is worse than no macro at all.
#}

{# ------------------------------------------------------------------ money cast
   Fixed-precision money. Warehouses disagree on the maximum precision and on how a
   bare `numeric` behaves, so the type is named once here rather than in 40 models.
#}
{% macro money_type() -%}
    {{ return(adapter.dispatch('money_type', 'analytics')()) }}
{%- endmacro %}

{% macro default__money_type() -%}
    numeric(28, 6)
{%- endmacro %}

{% macro bigquery__money_type() -%}
    {# BigQuery caps NUMERIC at precision 38, scale 9; 28,6 is inside that. #}
    numeric
{%- endmacro %}

{% macro duckdb__money_type() -%}
    decimal(28, 6)
{%- endmacro %}


{# ------------------------------------------------------------- current timestamp
   `current_timestamp` is ANSI but returns different types: TIMESTAMP_LTZ on Snowflake,
   TIMESTAMP WITH TIME ZONE on BigQuery. Normalize to a naive UTC timestamp so a
   downstream comparison against a cast column does not fail on tz-awareness.
#}
{% macro utc_now() -%}
    {{ return(adapter.dispatch('utc_now', 'analytics')()) }}
{%- endmacro %}

{% macro default__utc_now() -%}
    cast(current_timestamp at time zone 'UTC' as timestamp)
{%- endmacro %}

{% macro bigquery__utc_now() -%}
    cast(current_timestamp() as datetime)
{%- endmacro %}

{% macro snowflake__utc_now() -%}
    cast(convert_timezone('UTC', current_timestamp()) as timestamp_ntz)
{%- endmacro %}

{% macro duckdb__utc_now() -%}
    cast(now() at time zone 'UTC' as timestamp)
{%- endmacro %}


{# ------------------------------------------------------------------- table config
   Clustering has a different name and different limits on every platform, and an
   unsupported config key is a hard error rather than a warning. Centralize it so a
   platform move is one file.

   Usage:  {{ config(**cluster_config(['ordered_date'])) }}
#}
{% macro cluster_config(columns) %}
    {% if target.type == 'snowflake' %}
        {{ return({'cluster_by': columns}) }}
    {% elif target.type == 'bigquery' %}
        {# BigQuery: partition on the date, cluster on the rest. Max 4 cluster columns. #}
        {{ return({
            'partition_by': {'field': columns[0], 'data_type': 'date', 'granularity': 'day'},
            'cluster_by': columns[1:5]
        }) }}
    {% elif target.type in ('databricks', 'spark') %}
        {{ return({'file_format': 'delta', 'partition_by': columns[0]}) }}
    {% else %}
        {# DuckDB, Postgres: no clustering. Returning {} is the point — the model still
           builds, it just does not carry a config the adapter would reject. #}
        {{ return({}) }}
    {% endif %}
{% endmacro %}


{# ------------------------------------------------------- incremental strategy
   Not every adapter supports every strategy, and an unsupported one is a hard error
   on the *second* run — the first run does a full create and never exercises it.

     merge          Snowflake, BigQuery, Databricks, Spark
     delete+insert  DuckDB, Postgres, Redshift, Snowflake
     append         everywhere, but only safe when rows are immutable

   `merge` is preferred where available: it is one atomic statement. `delete+insert`
   is two, and on a non-transactional warehouse a failure between them leaves a hole.
#}
{% macro incremental_upsert_strategy() %}
    {% if target.type in ('snowflake', 'bigquery', 'databricks', 'spark') %}
        {{ return('merge') }}
    {% else %}
        {{ return('delete+insert') }}
    {% endif %}
{% endmacro %}

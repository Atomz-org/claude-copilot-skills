{{ config(materialized='table') }}

-- Required by every cumulative metric, every offset_window, and every
-- join_to_timespine in models/semantic/. The end_date deliberately runs into the
-- future: a spine that stops before the fact data does silently truncates the tail
-- of every cumulative metric, and nothing errors.
--
-- Deliberately NOT connector-gated: it has no refs, costs one small table, and a
-- gated spine would fail `dbt parse` for any tenant with the semantic layer on and
-- that connector off.
--
-- Start date [NEEDS INPUT]: set at or before the earliest `start_years` floor
-- across tenants (dbt_project.yml vars). 2019-01-01 covers the demo data.
--
-- Portability notes (each cost a build to learn in example-order-revenue-mart):
-- 1. A bare `dateadd(year, 2, current_date)` is Snowflake dialect. DuckDB spells it
--    date_add, BigQuery reverses the arguments. dbt.dateadd compiles on all of them.
-- 2. The block-assignment form is required: cross-database macros emit text, so
--    `set spine_end = dbt.dateadd(...)` captures nothing.
-- 3. Jinja parses SQL comments, so macro names here are written plainly.

{% set spine_end %}{{ dbt.dateadd("year", 2, "current_date") }}{% endset %}

{{ dbt_utils.date_spine(
    datepart="day",
    start_date="cast('2019-01-01' as date)",
    end_date=spine_end
) }}

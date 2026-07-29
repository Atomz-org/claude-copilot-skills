{{ config(materialized='table') }}

-- Required by every cumulative metric, every offset_window, and every
-- join_to_timespine in models/semantic/. The end_date deliberately runs into the
-- future: a spine that stops before the fact data does silently truncates the tail
-- of every cumulative metric, and nothing errors.
--
-- Three portability notes, each of which costs a build to learn:
--
-- 1. A bare `dateadd(year, 2, current_date)` is Snowflake/Redshift dialect. DuckDB
--    spells it date_add, BigQuery spells it DATE_ADD with the arguments the other way
--    round. dbt.dateadd is the cross-database macro that compiles on all of them.
--
-- 2. The block-assignment form below is required. dbt's cross-database macros emit
--    text rather than returning a value, so `set spine_end = dbt.dateadd(...)`
--    captures nothing and the spine compiles to `( + cast( as bigint) * interval 1 )`.
--
-- 3. Jinja parses SQL comments. A Jinja expression written inside a `--` comment is
--    evaluated, not ignored — which is why the macro names above are written plainly.

{% set spine_end %}{{ dbt.dateadd("year", 2, "current_date") }}{% endset %}

{{ dbt_utils.date_spine(
    datepart="day",
    start_date="cast('2019-01-01' as date)",
    end_date=spine_end
) }}

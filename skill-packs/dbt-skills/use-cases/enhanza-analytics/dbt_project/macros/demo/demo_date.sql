--Purpose: as we build DEMO data based on real data, we want to substitute the real dates with fake actual dates
--Usage: converts date to the year specified in dbt_project.yml, in DEMO only

{%- macro demo_date(date_column) -%}
(
  {%- set current_year = run_started_at.year -%}
  {%- set delta = current_year - var('demo_max_year', 2023) -%}
  {%- set previous_year = current_year - delta -%}
  {%- set before_previous_year = current_year - delta - 1 -%}
  DATE(
    CASE
      WHEN EXTRACT(YEAR FROM {{ date_column }}) = {{ before_previous_year }} THEN {{ current_year }} - 1
      WHEN EXTRACT(YEAR FROM {{ date_column }}) = {{ previous_year }} THEN {{ current_year }}
      ELSE EXTRACT(YEAR FROM {{ date_column }})
    END,
    EXTRACT(MONTH FROM {{ date_column }}),
    LEAST(
      EXTRACT(DAY FROM {{ date_column }}),
      EXTRACT(DAY FROM LAST_DAY(
        DATE(
          CASE
            WHEN EXTRACT(YEAR FROM {{ date_column }}) = {{ before_previous_year }} THEN {{ current_year }} - 1
            WHEN EXTRACT(YEAR FROM {{ date_column }}) = {{ previous_year }} THEN {{ current_year }}
            ELSE EXTRACT(YEAR FROM {{ date_column }})
          END,
          EXTRACT(MONTH FROM {{ date_column }}),
          1
        )
      ))
    )
  )
)
{%- endmacro -%}
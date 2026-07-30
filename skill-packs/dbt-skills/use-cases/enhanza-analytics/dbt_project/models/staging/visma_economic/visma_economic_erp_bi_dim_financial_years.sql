{{ config(materialized='ephemeral', enabled = var('is_visma_economic_enabled', false)) }}


with pre AS (
  SELECT
    CASE
      -- Order Financial Year by date
      WHEN current_date() BETWEEN PARSE_DATE('%Y-%m-%d', fromDate)
      AND PARSE_DATE('%Y-%m-%d', toDate) THEN 0
      WHEN current_date() > PARSE_DATE('%Y-%m-%d', toDate) THEN -1
      ELSE 1
    END AS multi,
    OrgId,
    OrgId || '-' || year as FinancialYearId,
    year Id,
    PARSE_DATE('%Y-%m-%d', fromDate) FromDate,
    PARSE_DATE('%Y-%m-%d', toDate) ToDate,
    CONCAT(
      FORMAT_TIMESTAMP("%y%m%d", PARSE_DATE('%Y-%m-%d', fromDate)),
      "-",
      FORMAT_TIMESTAMP("%y%m%d", PARSE_DATE('%Y-%m-%d', toDate))
    ) FinancialYear,
  FROM
    {{ source('visma_economic_api', 'accounting_years') }}
),
pre2 AS (
  SELECT
    ROW_NUMBER() OVER (
      PARTITION BY OrgId,
      multi
      ORDER BY
        fromdate DESC
    ) AS rn_past,
    ROW_NUMBER() OVER (
      PARTITION BY OrgId,
      multi
      ORDER BY
        fromdate ASC
    ) AS rn_future,
    *
  FROM
    pre
)
SELECT
  cast(OrgId as string) as OrgId
  , FinancialYearId
  , cast(Id as STRING)  as Id
  , FromDate
  , ToDate
  , FinancialYear
  , CASE
    WHEN multi = -1 THEN rn_past * multi
    WHEN multi = 1 THEN rn_future
    ELSE multi
  END AS FyCounter
, {{ add_erp_fields(columns=['FinancialYearId']) }}
FROM
  pre2
order by
  OrgId,
  FyCounter desc

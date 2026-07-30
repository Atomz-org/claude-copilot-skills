{{ config(materialized='ephemeral', enabled = var('is_visma_eaccounting_enabled', false)) }}


with pre AS (
  SELECT
    CASE
      -- Order Financial Year by date
      WHEN current_date() BETWEEN StartDate
      AND EndDate THEN 0
      WHEN current_date() > EndDate THEN -1
      ELSE 1
    END multi
    , OrgId
    , OrgId || '-' || Id FinancialYearId
    , Id
    , StartDate FromDate
    , EndDate ToDate
    , CONCAT(
      FORMAT_TIMESTAMP("%y%m%d", StartDate),
      "-",
      FORMAT_TIMESTAMP("%y%m%d", EndDate)
    ) FinancialYear,
  FROM
    {{ source('visma_eaccounting_api', 'fiscalyears') }}
),
pre2 AS (
  SELECT
    ROW_NUMBER() OVER (
      PARTITION BY OrgId,
      multi
      ORDER BY
        FromDate DESC
    ) AS rn_past
    , ROW_NUMBER() OVER (
      PARTITION BY OrgId,
      multi
      ORDER BY
        FromDate ASC
    ) AS rn_future
    , *
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
  OrgId
  , FyCounter desc
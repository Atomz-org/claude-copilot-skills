{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}


with pre AS (
  SELECT
    CASE
      -- Order Financial Year by date
      WHEN current_date() BETWEEN FromDate
      AND ToDate THEN 0
      WHEN current_date() > ToDate THEN -1
      ELSE 1
    END AS multi,
    OrgId,
    OrgId || '-' || Id as FinancialYearId,
    Id,
    FromDate,
    ToDate,
    CONCAT(
      FORMAT_TIMESTAMP("%y%m%d", FromDate),
      "-",
      FORMAT_TIMESTAMP("%y%m%d", ToDate)
    ) FinancialYear,
  FROM
    {{ source('fortnox_api', 'financial_years') }}
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
  * except(rn_past,rn_future,multi),
  CASE
    WHEN multi = -1 THEN rn_past * multi
    WHEN multi = 1 THEN rn_future
    ELSE multi
  END AS FyCounter
FROM
  pre2
order by
  OrgId,
  FyCounter desc
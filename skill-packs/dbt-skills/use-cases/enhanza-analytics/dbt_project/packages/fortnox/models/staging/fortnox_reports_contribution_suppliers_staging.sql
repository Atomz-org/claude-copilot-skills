{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}

WITH
  invoice_dates AS (
  SELECT
    GENERATE_DATE_ARRAY( MIN(InvoiceDate), MAX(InvoiceDate), INTERVAL 1 DAY ) AS dt
  FROM
    {{ ref('fortnox_bi_fact_invoices_staging') }} ),
  pre AS (
  SELECT
    ROW_NUMBER() OVER (PARTITION BY i.ArticleNumber, i.InvoiceNo ORDER BY si.InvoiceDate DESC ) AS rn,
    i.OrgId,
    c.OrgName,
    i.InvoiceDate,
    i.InvoiceNo,
    i.ArticleNumber,
    i.SalesValue,
    i.ContributionValue,
    i.DeliveredQuantity,
    si.InvoiceDate last_seen_supplier_invoice_date,
    si.SupplierInvoiceNo last_seen_supplier_supplierid,
  IF
    (si.Price IS NULL, SAFE_DIVIDE( ( i.SalesValue - i.ContributionValue ), i.DeliveredQuantity ), si.Price
      -- * if(i.DeliveredQuantity < 0, -1, 1)
      ) last_seen_supplier_purchase_price,
    Name AS SupplierName
  FROM
    {{ ref('fortnox_bi_fact_invoice_rows_staging') }} i
  LEFT JOIN
    {{ ref('fortnox_bi_fact_supplier_invoice_rows_staging') }} si
  ON
    i.ArticleNumber = si.ArticleNumber
    AND si.InvoiceDate <= i.InvoiceDate
  LEFT JOIN
    {{ ref('fortnox_bi_dim_suppliers_staging') }} s
  ON
    s.SupplierId = si.SupplierId
  LEFT JOIN
    {{ ref('fortnox_bi_dim_company_staging') }} c on c.OrgId = i.OrgId
  WHERE
    i.ArticleNumber IS NOT NULL
    AND i.ArticleNumber != "" )
SELECT
  pre.* EXCEPT(SupplierName, rn),
  a.Description,
  IFNULL(pre.SupplierName, a.SupplierName) SupplierName,
  pre.SalesValue - last_seen_supplier_purchase_price * DeliveredQuantity SupplierMargin
FROM
  pre
LEFT JOIN
  {{ ref('fortnox_bi_dim_articles_staging') }} a
ON
  pre.ArticleNumber = a.ArticleNumber
WHERE
  rn = 1
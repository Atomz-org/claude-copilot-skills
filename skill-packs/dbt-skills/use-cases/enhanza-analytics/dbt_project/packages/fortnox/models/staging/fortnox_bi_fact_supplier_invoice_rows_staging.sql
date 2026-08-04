{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

SELECT
  i.InvoiceDate,
  i.DueDate,
  i.FinalPayDate,
  i.GivenNumber as SupplierInvoiceNo,
  i.InvoiceNumber,
  i.Currency,
  i.CurrencyRate,
  i.Credit as isCredit,
  i.Booked as isBooked,
  {{ blank_to_null('r.ArticleNumber') }} as ArticleNumber,
  r.Account,
  r.Credit - r.Debit as Balance,
  r.Quantity,
  r.Price * i.CurrencyRate as Price,
  r.Total * i.CurrencyRate as Total,
  {{ blank_to_null('r.Code') }} Code,
  {{ blank_to_null('r.TransactionInformation') }} TransactionInformation,
  {{ blank_to_null('r.Unit') }} Unit,
  {{blank_to_null('i.YourReference') }} YourReference,
  i.OrgId,
  i.OrgId || '-' || {{ blank_to_null('i.GivenNumber') }} as SupplierInvoiceId,
  i.OrgId || '-' || {{ blank_to_null('i.SupplierNumber') }} as SupplierId,
  i.OrgId || '-' || {{ blank_to_null('r.ArticleNumber') }} as ArticleId,
  fy.OrgId || '-' || fy.Id || '-' || r.Account as AccountId,
  i.OrgId || '-' || {{ blank_to_null('r.Project') }} as ProjectId,
  i.OrgId || '-' || {{ blank_to_null('r.CostCenter') }} as CostCenterId,
FROM
  {{ source('fortnox_api', 'supplier_invoices') }} i
  cross join unnest(SupplierInvoiceRows) as r
  left join {{ source('fortnox_api', 'financial_years') }} fy 
  on date(i.InvoiceDate) between fy.FromDate and fy.ToDate and fy.OrgId=i.OrgId
order by
  i.InvoiceDate desc
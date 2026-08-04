{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  i.DocumentNumber,
  initcap( {{ blank_to_null('i.OurReference') }} ) as OurReference,
  i.Currency,
  r.DeliveredQuantity,
  -- Multiply Article quantity with unit price
  r.DeliveredQuantity * r.price
  -- Convert from foreign currency to SEK
  -- * i.CurrencyRate *
  -- Apply any % discount rows
  * IF (
    DiscountType = "PERCENT",
    1 - r.Discount / 100,
    1
  )
  -- Apply any amount discount rows
  - IF (
    DiscountType = "AMOUNT",
    r.Discount,
    0
  ) as SalesValue,
  r.ContributionValue as ContributionValue,
  ContractDate,
  Continuous,
  ContractLength,
  InvoiceInterval,
  InvoicesRemaining,
  PeriodEnd,
  PeriodStart,
  Active,
  i.Status,
  i.OrgId,
  i.OrgId || '-' || i.DocumentNumber ContractId,
  i.OrgId || '-' || {{ blank_to_null('r.ArticleNumber') }} as ArticleId,
  i.OrgId || '-' || {{ blank_to_null('i.CustomerNumber') }} as CustomerId,
  null as AccountId,
  i.OrgId || '-' || {{ blank_to_null('r.CostCenter') }} as CostCenterId,
  i.OrgId || '-' || {{ blank_to_null('r.Project') }} ProjectId,
FROM
  {{ source('fortnox_api', 'contracts') }} i
  cross join UNNEST(InvoiceRows) r
WHERE
  r.price <> 0

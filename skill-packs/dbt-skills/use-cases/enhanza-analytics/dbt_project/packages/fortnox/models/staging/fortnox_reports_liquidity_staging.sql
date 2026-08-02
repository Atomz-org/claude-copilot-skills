{{ config(alias=(model_alias(model.name)), enabled = var('is_fortnox_enabled', 'False') | as_bool) }}


with b as (
  -- Bank Account Balance (1930)
  select
    "Excluding tax" as Category,
    "liquidity" as Type,
    cast(a.Number as string) as Id,
    current_date() as Date,
    "Transaction Date" as DateType,
    BalanceBroughtForward as Balance
  from
    {{ ref('fortnox_bi_dim_accounts_staging') }} a
    left join {{ ref('fortnox_bi_dim_financial_years_staging') }} f on a.FinancialYearId = f.FinancialYearId
  where
    f.FyCounter = 0
    and a.Number in (1930,2330)
    and BalanceBroughtForward <> 0
),
i as (
  -- Customer Invoices (unpaid with future due dates)
  select
    "Including tax" as Category,
    "Invoices" as Type,
    cast(InvoiceNo as string) as Id,
    DueDate as Date,
    "Due date" as DateType,
    Balance,
  from
    {{ ref('fortnox_bi_fact_invoices_staging') }}
  where Balance <> 0
    and DueDate between current_date()
    and date_add(current_date(), interval 12 month)
),
-- Supplier Invoices (unpaid with future due dates)
si as (
  select
    "Including tax" as Category,
    "Supplier invoices" as Type,
    SupplierInvoiceNo as Id,
    DueDate as Date,
    "Due date" as DateType,
    Balance * -1
  from
    {{ ref('fortnox_bi_fact_supplier_invoices_staging') }}
  where DueDate between current_date()
    and date_add(current_date(), interval 12 month)
),
o as (
  -- Customer Orders (future DeliverDate and no related invoices)
  select
    "Excluding tax" as Category,
    "Orders" as Type,
    cast(OrderNum as string) as Id,
    DeliveryDate as Date,
    "Delivery date" as DateType,
  sum(SalesValue) as SalesValue
  from
    {{ ref('fortnox_bi_fact_order_rows_staging') }}
  where
    InvoiceReference = "0"
    and DeliveryDate between current_date()
    and date_add(current_date(), interval 12 month)
    -- and DueDate between current_date() and date_add(current_date(), interval 12 month)
    group by 1,2,3,4,5
),
offers as (
  -- Customer offers (future DeliverDate and no related invoices)
  select
    "Excluding tax" as Category,
    "Offers" as Type,
    cast(OfferNo as string) as Id,
    ExpireDate as Date,
    "Date of validity" as DateType,
    Net as Balance
  from
    {{ ref('fortnox_bi_fact_offers_staging') }}
  where
   Net <> 0
    and OrderReference = "0"
    and ExpireDate between current_date()
    and date_add(current_date(), interval 12 month)
    -- and DueDate between current_date() and date_add({current_date(), interval 12 month)
),
-- Puchase Orders
po as (
  with po_si as (
    -- Find value of connected supplier invoices
    select
      p.id,
      --m.id as si_id,
      sum(si.Total * si.CurrencyRate) as value
    FROM
      {{ source('fortnox_api', 'purchaseorders') }} p
      cross join unnest(matches) m
      left join {{ source('fortnox_api', 'supplier_invoices') }} si on si.SupplierNumber = m.id
    where m.type = "SUPPLIER_INVOICE"
    group by
      p.id
  )
  select
    "Excluding tax" as Category,
    "Puchase orders" as Type,
    cast(p.id as string),
    deliveryDate,
    "Delivery date" as DateType,
    -- p.orderValue,
    -- si.value as supplier_value,
    -- substract value from related supplier invoices from purchase order value
    (p.orderValueInSEK - ifnull(si.value, 0)) * -1 as Balance
  from
    {{ source('fortnox_api', 'purchaseorders') }} p
    left join po_si as si on p.id = si.id
  where voided is false
    and DeliveryDate between current_date()
    and date_add(current_date(), interval 12 month)
  order by
    p.id desc
)
select
  *
from
  b
union all
select
  *
from
  i
union all
select
  *
from
  si
union all
select
  *
from
  o
union all
select
  *
from
  offers
union all
select
  *
from
  po
where
  Balance <> 0
order by
  Type,
  Date desc
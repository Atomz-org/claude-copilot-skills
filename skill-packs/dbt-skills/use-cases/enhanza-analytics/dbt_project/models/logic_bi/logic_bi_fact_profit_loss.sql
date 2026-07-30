{{ config(
    alias=(model_alias(model.name)),
        enabled = any_source_enabled(['fortnox', 'seventime', 'tripletex', 'visma_eaccounting', 'visma_economic'])
) }}

{% set budget_enabled = model_is_provided('fact_budgets') %}
{%- set ref_type = true -%}

with docs as ( --get all references for ReferenceNumber
  select 
    'i' || '-' || f.InvoiceId DocId
    , d.Name
    , f.DataSource
  from {{ ref('erp_bi_fact_invoices') }} f
  left join {{ ref('erp_bi_dim_customers') }} d
    on d.CustomerIdERP=f.CustomerIdERP
  group by 1,2,3

{% if var('is_fortnox_enabled') %}
    union all
  select 
    's' || '-' || f.SupplierInvoiceId DocId
    , d.Name
    , f.DataSource
  from {{ ref('erp_bi_fact_supplier_invoice_rows') }} f
  left join {{ ref('erp_bi_dim_suppliers') }} d
    on d.SupplierIdERP=f.SupplierIdERP
  group by 1,2,3
    union all
  select 
    'ip' || '-' || f.InvoiceId DocId
    , d.Name
    , 'Fortnox' DataSource
  from {{ ref('fortnox_bi_fact_invoice_payments_staging') }} f
  left join {{ ref('erp_bi_dim_customers') }} d
    on d.CustomerId=f.CustomerId
    and d.DataSource = 'Fortnox'
  group by 1,2,3
{% endif %}

)

, v0 as ( --prepare vouchers data
  select
    v.OrgIdERP OrgId
    , v.AccountIdERP AccountId
    , v.CostCenterIdERP CostCenterId
    , v.ProjectIdERP ProjectId
    , v.FinancialYearIdERP FinancialYearId
    , last_day(v.TransactionDate) TransactionDate
    , v.VoucherSeries
    , v.VoucherNumber
    , v.TransactionInformation
    , v.DescriptionRows
    , v.Description
    , v.DataSource
    , v.DefaultCurrency
    , initcap(regexp_replace(regexp_replace(lower(trim(v.ReferenceType)), r'(\w)(invoice|payment)', r'\1 \2'), r'\s+', ' ')) ReferenceType
    {% if ref_type %}
      , case
        when lower(v.ReferenceType) like '%invoice%' and not lower(v.ReferenceType) like '%supplier%' then 'i' || '-' || v.OrgId || '-' || v.ReferenceNumber
        when lower(v.ReferenceType) like '%supplier%' then 's' || '-' || v.OrgId || '-' || v.ReferenceNumber
        when lower(v.ReferenceType) like '%invoice%' and lower(v.ReferenceType) like '%payment%' then 'ip' || '-' || v.OrgId || '-' || v.ReferenceNumber
        else null
      end 
    {% else %} NULL {% endif %}  RefId
    , {{ blank_to_null ('v.ReferenceNumber') }} ReferenceNumber
    , sum(v.Amount * CASE
          WHEN v.DataSource IN ('Tripletex', 'Visma e-conomic') THEN -1
          ELSE 1
        END
      ) Amount
  from {{ ref('erp_bi_fact_vouchers') }} v
  -- joining global chart of accounts and current mapping to get new filtering
  left join {{ ref('erp_bi_dim_accounts') }} a
    on a.AccountIdERP = v.AccountIdERP
  left join {{ ref('categories_x_mapping') }} cxm
    on cxm.DimensionIdERP = split(a.AccountId, '-')[offset(0)] || '-' || a.Number
  where cxm.Level1ID in ('1-1003', '1-1004') --revenues and costs
  group by all
)

, pnl as ( --old version of PnL ends with this; expanded to host Budgets
  select
    v0.* except(RefId)
    , docs.Name ReferenceTargetName
    , cast(null as float64) BudgetAmount
    , i.OurReference SalesRep
    , c.OurReference SalesRepCustomer
  from v0
  left join docs
    on docs.DocId = v0.RefId
    and docs.DataSource = v0.DataSource
  left join {{ ref('erp_bi_fact_invoices') }} i
    on cast(i.InvoiceNo as string) = v0.ReferenceNumber
    and v0.ReferenceType in ('Invoice', 'Invoice Payment')
    and v0.OrgId = i.OrgIdERP
    and v0.DataSource = i.DataSource
  left join {{ ref('erp_bi_dim_customers') }} c
    on c.CustomerId = i.CustomerId
)

{% if budget_enabled %}
, budgets as (
  select
    OrgIdERP OrgId
    , AccountIdERP AccountId
    , CostCenterIdERP CostCenterId
    , 'BUDGET' ProjectId
    , FinancialYearIdERP FinancialYearId
    , BudgetDate TransactionDate
    , cast(null as string) VoucherSeries
    , null VoucherNumber
    , cast(null as string) TransactionInformation
    , cast(null as string) DescriptionRows
    , cast(null as string) `Description`
    , DataSource
    , DefaultCurrency
    , 'BUDGET' ReferenceType
    , 'BUDGET' ReferenceNumber
    , null Amount
    , 'BUDGET'  ReferenceTargetName
    , cast(Amount as float64) BudgetAmount
    , cast(null as string) SalesRep
    , cast(null as string) SalesRepCustomer
  from {{ ref('erp_bi_fact_budgets') }}
)
{% endif %}

, fin as (
  select * from pnl
  {% if budget_enabled %}
  union all
  select * from budgets
  {% endif %}
)

select * from fin
order by TransactionDate desc
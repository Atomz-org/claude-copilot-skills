{{ config(
    alias=(model_alias(model.name)),
    enabled = any_source_enabled(['fortnox', 'seventime', 'visma_eaccounting', 'upsales'])
) }}

{% set invoice_rows_enabled = model_is_provided('fact_invoice_rows') %}
{% set order_rows_enabled = model_is_provided('fact_order_rows') %}
{% set invoice_enabled = model_is_provided('fact_invoices') %}
{% set order_enabled = model_is_provided('fact_orders') %}
{% set offer_enabled = model_is_provided('fact_offers') %}
{% set customer_enabled = model_is_provided('dim_customers_suppliers') %}
{% set article_enabled = model_is_provided('dim_articles') %}
{% set employee_enabled = model_is_provided('dim_employees') %}
{% set account_enabled = model_is_provided('dim_accounts') %}

{%- set erp_invoice_query = '' -%}
{%- set erp_offers_query = '' -%}
{%- set erp_orders_query = '' -%}
{%- set erp_opportunities_query = '' -%}

{% if invoice_rows_enabled %}
  {%- set erp_invoice_query -%}
    select
      i.InvoiceDate Date
      , i.InvoiceId DocumentId
      , 'Invoice' DocumentType
      , cast(i.InvoiceNo as string) DocumentNumber
      , i.OurReference SalesRep
      , cxm.Level1 SalesRepGroup
      , cxm.Level2 SalesRepSubGroup
      , cxm.Level3 SalesRepSubSubGroup
      , cxm.Level1ID SalesRepGroupId
      , cxm.Level2ID SalesRepSubGroupId
      , cxm.CategoryId SalesRepSubSubGroupId
      , i.SalesValue
      , i.ContributionValue
      , i.DeliveredQuantity Quantity
      , {% if pad %} i.PriceAfterDiscount {% else %} NULL {% endif %}  PriceAfterDiscount
      , i.PriceBeforeDiscount
      {% if customer_enabled %}
        , if(i.InvoiceDate > c.FirstInvoiceDate, FALSE, TRUE) isNewCustomer
      {% else %}
        , cast(null as boolean) isNewCustomer
      {% endif %}
      {% if invoice_enabled %}
        , labels.Labels
      {% else %}
        , cast(null as string) Labels
      {% endif %}
      {% if article_enabled %}
        , (i.OrgId || '-' || art.SupplierNumber || '-' || regexp_extract(art.ArticleIdERP, r'-([^-\s]+)$')) || '-S' SupplierId
      {% else %}
        , cast(null as string) SupplierId
      {% endif %}
      , i.OrgIdERP OrgId
      , i.ArticleIdERP ArticleId
      , i.CustomerIdERP || '-C' CustomerId
      , i.CostCenterIdERP CostCenterId
      , i.ProjectIdERP ProjectId
      , fy.FinancialYearIdERP FinancialYearId
      {% if account_enabled %}
        , i.AccountIdERP AccountId
      {% else %}
        , cast(null as string) AccountId
      {% endif %}
      , i.DataSource
      , i.DefaultCurrency
    from {{ ref('erp_bi_fact_invoice_rows') }} i
    left join {{ ref('erp_bi_dim_financial_years') }} fy
      on split(fy.FinancialYearId, '-')[safe_offset(0)]=cast(i.OrgId as string)
      and i.InvoiceDate between fy.FromDate and fy.ToDate
      and i.DataSource=fy.DataSource
    {% if customer_enabled %}
      left join {{ ref('erp_bi_dim_customers') }} c
        on c.CustomerIdERP = i.CustomerIdERP
    {% endif %}
    {% if invoice_enabled %}
      left join {{ ref('erp_bi_fact_invoices') }} labels
        on labels.InvoiceIdERP = i.InvoiceIdERP
    {% endif %}
    {% if article_enabled %}
      left join {{ ref('erp_bi_dim_articles') }} art
        on art.ArticleIdERP = i.ArticleIdERP
    {% endif %}
    left join {{ ref('categories_x_mapping') }} cxm
      on cxm.DimensionIdERP = i.OrgIdERP || '|' || i.OurReference
      and cxm.DimensionTable='dim_employees'
      and cxm.DimensionColumn='EmployeeId'
  {%- endset -%}
{% endif %}

{% if offer_enabled %}
  {%- set erp_offers_query -%}
    select
      o.OfferDate Date
      , o.OfferId DocumentId
      , 'Quote' DocumentType
      , o.OfferNo DocumentNumber
      , o.OurReference SalesRep
      , cxm.Level1 SalesRepGroup
      , cxm.Level2 SalesRepSubGroup
      , cxm.Level3 SalesRepSubSubGroup
      , cxm.Level1ID SalesRepGroupId
      , cxm.Level2ID SalesRepSubGroupId
      , cxm.CategoryId SalesRepSubSubGroupId
      , o.Net SalesValue
      , o.ContributionValue
      , null Quantity
      , null PriceAfterDiscount
      , null PriceBeforeDiscount
      {% if customer_enabled %}
        , if(o.OfferDate > c.FirstInvoiceDate, FALSE, TRUE) isNewCustomer
      {% else %}
        , cast(null as boolean) isNewCustomer
      {% endif %}
      , o.Labels
      , cast(null as string) SupplierId
      , o.OrgIdERP OrgId
      , cast(null as string) ArticleId
      , o.CustomerIdERP || '-C' CustomerId
      , o.CostCenterIdERP CostCenterId
      , o.ProjectIdERP ProjectId
      , fy.FinancialYearIdERP FinancialYearId
      , cast(null as string) AccountId
      , o.DataSource
      , o.DefaultCurrency
      from {{ ref('erp_bi_fact_offers') }} o
      left join {{ ref('erp_bi_dim_financial_years') }} fy
        on split(fy.FinancialYearId, '-')[safe_offset(0)]=cast(o.OrgId as string)
        and o.OfferDate between fy.FromDate and fy.ToDate
        and o.DataSource=fy.DataSource
      {% if customer_enabled %}
        left join {{ ref('erp_bi_dim_customers') }} c
          on c.CustomerIdERP = o.CustomerIdERP
      {% endif %}
      left join {{ ref('categories_x_mapping') }} cxm
        on cxm.DimensionIdERP = o.OrgIdERP || '|' || o.OurReference
        and cxm.DimensionTable='dim_employees'
        and cxm.DimensionColumn='EmployeeId'
      where 
      o.OrderReference='0' 
      or o.OrderReference='' 
      or o.OrderReference is null
  {%- endset -%}
{% endif %}

{% if order_rows_enabled %}
  {%- set erp_orders_query -%}
    select
      o.OrderDate Date
      , o.OrderId DocumentId
      , 'Order' DocumentType
      , cast(o.OrderNum as string) DocumentNumber
      , o.OurReference SalesRep
      , cxm.Level1 SalesRepGroup
      , cxm.Level2 SalesRepSubGroup
      , cxm.Level3 SalesRepSubSubGroup
      , cxm.Level1ID SalesRepGroupId
      , cxm.Level2ID SalesRepSubGroupId
      , cxm.CategoryId SalesRepSubSubGroupId
      , case
        when o.DataSource = 'Fortnox' then o.OrderedValue
        else o.SalesValue
      end SalesValue
      , o.ContributionValue
      , o.OrderedQuantity Quantity
      , o.PriceAfterDiscount
      , o.PriceBeforeDiscount
      {% if customer_enabled %}
        , if(o.OrderDate > c.FirstInvoiceDate, FALSE, TRUE) isNewCustomer
      {% else %}
        , cast(null as boolean) isNewCustomer
      {% endif %}
      {% if order_enabled %}
        , labels.Labels
      {% else %}
        , cast(null as string) Labels
      {% endif %}
      {% if article_enabled %}
        , (o.OrgId || '-' || art.SupplierNumber || '-' || regexp_extract(art.ArticleIdERP, r'-([^-\s]+)$')) || '-S' SupplierId
      {% else %}
        , cast(null as string) SupplierId
      {% endif %}
      , o.OrgIdERP OrgId
      , o.ArticleIdERP ArticleId
      , o.CustomerIdERP || '-C' CustomerId
      , o.CostCenterIdERP CostCenterId
      , o.ProjectIdERP ProjectId
      , fy.FinancialYearIdERP FinancialYearId
      {% if account_enabled %}
        , o.AccountIdERP AccountId
      {% else %}
        , cast(null as string) AccountId
      {% endif %}
      , o.DataSource
      , o.DefaultCurrency
    from {{ ref('erp_bi_fact_order_rows') }} o
    left join {{ ref('erp_bi_dim_financial_years') }} fy
      on split(fy.FinancialYearId, '-')[safe_offset(0)]=cast(o.OrgId as string)
      and o.OrderDate between fy.FromDate and fy.ToDate
    {% if customer_enabled %}
      left join {{ ref('erp_bi_dim_customers') }} c
        on c.CustomerIdERP = o.CustomerIdERP
    {% endif %}
    {% if order_enabled %}
    left join {{ ref('erp_bi_fact_orders') }} labels
      on labels.OrderIdERP = o.OrderIdERP
    {% endif %}
    {% if article_enabled %}
      left join {{ ref('erp_bi_dim_articles') }} art
        on art.ArticleIdERP = o.ArticleIdERP
    {% endif %}
    left join {{ ref('categories_x_mapping') }} cxm
        on cxm.DimensionIdERP = o.OrgIdERP || '|' || o.OurReference
        and cxm.DimensionTable='dim_employees'
        and cxm.DimensionColumn='EmployeeId'
    where 
      o.InvoiceReference='0' 
      or o.InvoiceReference='' 
      or o.InvoiceReference is null
  {%- endset -%}
{% endif %}

{% if (any_source_enabled(['upsales']) | as_bool) %}
  {%- set upsales_opportunities_query -%}
    select
      o.OpportunityDate Date
      , o.OpportunityId DocumentId
      , 'Opportunity' DocumentType
      , cast(o.OpportunityNo as string) DocumentNumber
      , o.OurReference SalesRep
      , cxm.Level1 SalesRepGroup
      , cxm.Level2 SalesRepSubGroup
      , cxm.Level3 SalesRepSubSubGroup
      , cxm.Level1ID SalesRepGroupId
      , cxm.Level2ID SalesRepSubGroupId
      , cxm.CategoryId SalesRepSubSubGroupId
      , o.SalesValue
      , o.ContributionValue
      , o.Quantity
      , null PriceAfterDiscount
      , null PriceBeforeDiscount
      {% if customer_enabled %}
        , if(o.OpportunityDate > c.FirstInvoiceDate, FALSE, TRUE) isNewCustomer
      {% else %}
        , cast(null as boolean) isNewCustomer
      {% endif %}
      , cast(null as string) Labels
      {% if article_enabled %}
        , (o.OrgId || '-' || art.SupplierNumber || '-' || regexp_extract(art.ArticleIdERP, r'-([^-\s]+)$')) || '-S' SupplierId
      {% else %}
        , cast(null as string) SupplierId
      {% endif %}
      , o.OrgId || '-' || 'ds_upsales' OrgId
      , o.ArticleId || '-' || 'ds_upsales' ArticleId
      , o.CustomerId || '-' || 'ds_upsales' || '-C' CustomerId
      , cast(null as string) CostCenterId
      , cast(null as string) ProjectId
      , fy.FinancialYearId || '-' || 'ds_upsales' FinancialYearId
      , cast(null as string) AccountId
      , 'Upsales' DataSource
      , 'SEK' DefaultCurrency
    from {{ ref('upsales_bi_fact_opportunity_rows_staging') }} o
    left join {{ ref('upsales_erp_bi_dim_financial_years') }} fy
      on split(fy.FinancialYearId, '-')[safe_offset(0)]=cast(o.OrgId as string)
      and o.OpportunityDate between fy.FromDate and fy.ToDate
    {% if customer_enabled %}
      left join {{ ref('erp_bi_dim_customers') }} c
        on c.CustomerId = o.CustomerId
        and c.DataSource = 'Upsales'
    {% endif %}
    {% if article_enabled %}
      left join {{ ref('erp_bi_dim_articles') }} art
        on art.ArticleId = o.ArticleId
        and art.DataSource = 'Upsales'
    {% endif %}
    left join {{ ref('categories_x_mapping') }} cxm
        on cxm.DimensionIdERP = o.OrgId || '-ds_upsales' || '|' || o.OurReference
        and cxm.DimensionTable='dim_employees'
        and cxm.DimensionColumn='EmployeeId'
  {%- endset -%}
{% endif %}

{%- set all_queries = [erp_invoice_query, erp_offers_query, erp_orders_query, upsales_opportunities_query] -%}

{{ union_queries(all_queries, ' UNION ALL ') }}
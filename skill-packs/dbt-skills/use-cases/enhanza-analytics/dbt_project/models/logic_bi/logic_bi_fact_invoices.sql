{{ config(
    alias=(model_alias(model.name)),
        enabled = any_source_enabled(['fortnox', 'seventime', 'tripletex', 'visma_eaccounting', 'visma_economic'])
) }}

{%- set supplier_enabled = model_is_provided('fact_supplier_invoices') -%}
{%- set customer_query = '' -%}
{%- set supplier_query = '' -%}

{% set customer_query %}
    select
        cast(InvoiceNo as string) InvoiceNo
        , InvoiceIdERP InvoiceId
        , 'Customer' InvoiceType
        , InvoiceDate
        , DueDate
        , DueStatus
        , case
            when IsDue is true then 'isDue'
            else 'NotDue'
          end as Due
        , FinalPayDate
        , Net
        , AdministrationFee
        , Freight
        , TotalVAT
        , TotalToPay
        , Balance
        , CustomerIdERP || '-C' TargetId
        , OrgIdERP OrgId
        , DataSource
        , DefaultCurrency
    from {{ ref('erp_bi_fact_invoices') }}
{% endset %}

    {%- if supplier_enabled -%}
    {% set supplier_query %}
    select
        SupplierInvoiceNo InvoiceNo
        , SupplierInvoiceIdERP InvoiceId
        , 'Supplier' InvoiceType
        , InvoiceDate
        , DueDate
        , DueStatus
        , case
            when DueDate < current_date and Balance <> 0 then 'isDue'
            else 'NotDue'
          end as Due
        , FinalPayDate
        , Total - Vat - {% if admin_fee_sup %} AdministrationFee {% else %} 0 {% endif %} - Freight Net
        , AdministrationFee
        , Freight
        , Vat TotalVAT
        , Total TotalToPay
        , Balance
        , SupplierIdERP || '-S' TargetId
        , OrgIdERP OrgId
        , DataSource
        , DefaultCurrency
    from {{ ref('erp_bi_fact_supplier_invoices') }}
    {% endset %}
    {%- endif -%}

{%- set all_queries = [customer_query, supplier_query] -%}
{{ union_queries(all_queries) }}
{{ config(
    alias=(model_alias(model.name)),
        enabled = any_source_enabled(['fortnox', 'seventime', 'tripletex', 'upsales', 'visma_eaccounting', 'visma_economic'])
) }}

{%- set suppliers_enabled = model_is_provided('dim_suppliers') -%}
--This used to be two separate endpoints, geouped to serve as a dim table for grouped fact_invoices
--Requires careful check of grouping available!!!
{% set employee_enabled = model_is_provided('dim_employees') %}
{% set customer_cxm_cols = ['CustomerId', 'City'] %}
{% set supplier_cxm_cols = ['SupplierId', 'City'] %}

with customers0 as (
    select
        'Customer' TargetType
        , CustomerIdERP || '-C' TargetId
        , d0.Name || ' (' || CustomerNumber || ')' Name
        , {{ blank_to_null('d0.City') }} City
        , replace({{ blank_to_null('d0.Country') }}, 'Sverige', 'Sweden') Country
        , {{ blank_to_null('OurReference') }} SalesRepCustomer
        , cxm.Level1 SalesRepCustomerGroup
        , cxm.Level2 SalesRepCustomerSubGroup
        , cxm.Level3 SalesRepCustomerSubSubGroup
        , cxm.Level1ID SalesRepCustomerGroupId
        , cxm.Level2ID SalesRepCustomerSubGroupId
        , cxm.CategoryId SalesRepCustomerSubSubGroupId
        , FirstInvoiceDate 
        , d0.IsActive as isActive
        , d0.DataSource
        {{ cxm_select(customer_cxm_cols) }}
    from {{ ref('erp_bi_dim_customers') }} d0
      left join {{ ref('categories_x_mapping') }} cxm
        on cxm.DimensionIdERP = split(d0.CustomerIdERP, '-')[offset(0)] || '-' || regexp_extract(d0.CustomerIdERP, r'-([^-\s]+)$') || '|' || d0.OurReference
        and cxm.DimensionTable='dim_employees'
        and cxm.DimensionColumn='EmployeeId'
    {{ cxm_left_join(model_alias("dim_customers"), customer_cxm_cols) }}
)

, customers as (
    select
        TargetType
        , TargetId
        , Name
        , City
        , Country
        , SalesRepCustomer
        , SalesRepCustomerGroup
        , SalesRepCustomerSubGroup
        , SalesRepCustomerSubSubGroup
        , SalesRepCustomerGroupId
        , SalesRepCustomerSubGroupId
        , SalesRepCustomerSubSubGroupId
        , FirstInvoiceDate
        , CustomerGroup NameGroup
        , CustomerSubGroup NameSubGroup
        , CustomerSubSubGroup NameSubSubGroup
        , CustomerGroupId NameGroupId
        , CustomerSubGroupId NameSubGroupId
        , CustomerSubSubGroupId NameSubSubGroupId
        , CityGroup
        , CitySubGroup
        , CitySubSubGroup
        , CityGroupId
        , CitySubGroupId
        , CitySubSubGroupId
        , isActive
        , DataSource
    from customers0
)

{%- if suppliers_enabled -%}
, suppliers0 as (
    select
        'Supplier' TargetType
        , SupplierIdERP || '-S' TargetId
        , d0.Name || ' (' || SupplierNumber || ')' Name
        , {{ blank_to_null('City') }} City
        , replace({{ blank_to_null('Country') }}, 'Sverige', 'Sweden') Country
        , cast(null as string) SalesRepCustomer
        , cast(null as string) SalesRepCustomerGroup
        , cast(null as string) SalesRepCustomerSubGroup
        , cast(null as string) SalesRepCustomerSubSubGroup
        , cast(null as string) SalesRepCustomerGroupId
        , cast(null as string) SalesRepCustomerSubGroupId
        , cast(null as string) SalesRepCustomerSubSubGroupId
        , FirstInvoiceDate
        , d0.DataSource
        , d0.isActive as isActive
        {{ cxm_select(supplier_cxm_cols) }}
    from {{ ref('erp_bi_dim_suppliers') }} d0
    {{ cxm_left_join(model_alias("dim_suppliers"), supplier_cxm_cols) }}
)

, suppliers as (
    select
        TargetType
        , TargetId
        , Name
        , City
        , Country
        , SalesRepCustomer
        , SalesRepCustomerGroup
        , SalesRepCustomerSubGroup
        , SalesRepCustomerSubSubGroup
        , SalesRepCustomerGroupId
        , SalesRepCustomerSubGroupId
        , SalesRepCustomerSubSubGroupId
        , FirstInvoiceDate
        , SupplierGroup NameGroup
        , SupplierSubGroup NameSubGroup
        , SupplierSubSubGroup NameSubSubGroup
        , SupplierGroupId NameGroupId
        , SupplierSubGroupId NameSubGroupId
        , SupplierSubSubGroupId NameSubSubGroupId
        , CityGroup
        , CitySubGroup
        , CitySubSubGroup
        , CityGroupId
        , CitySubGroupId
        , CitySubSubGroupId
        , isActive
        , DataSource
    from suppliers0
)
{%- endif -%}

, fin as (
    select * from customers
    {% if suppliers_enabled %}
    union all
    select * from suppliers
    {% endif %}
)

select * from fin
order by TargetId
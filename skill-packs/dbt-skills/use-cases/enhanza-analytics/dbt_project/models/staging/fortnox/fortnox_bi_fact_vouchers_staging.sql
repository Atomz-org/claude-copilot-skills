{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

with docs as (
  select distinct
    cast(DocumentNumber as string) Id
    , CustomerNumber TargetId
    , 'INV' RefType
    , OrgId
  from {{ ref('fortnox_base_v2_invoices') }}
    union all
  select distinct
    cast(GivenNumber as string) Id
    , SupplierNumber TargetId
    , 'SUP' RefType
    , OrgId
  from {{ source('fortnox_api', 'supplier_invoices') }}
)

select
  date(v.TransactionDate) TransactionDate
  , r.Account
  , r.Credit - r.Debit Balance
  , v.Description
  , r.Description DescriptionRows
  , r.TransactionInformation
  , v.VoucherSeries
  , v.VoucherNumber
  , null AccountClass
  , if(ReferenceNumber = "", null, ReferenceNumber) ReferenceNumber
  , if(ReferenceType = "", null, ReferenceType) ReferenceType
  , v.OrgId
  , v.OrgId || '-' || v.Year FinancialYearId
  , v.OrgId || '-' || v.Year || '-' || r.Account AccountId
  , v.OrgId || '-' || if(r.CostCenter = "", null, r.CostCenter) CostCenterId
  , v.OrgId || '-' || if(r.Project = "", null, r.Project) ProjectId
  , v.OrgId || '-' || v.Year || '-' || if(VoucherSeries = "", null, VoucherSeries) VoucherSeriesId
  , case
    when v.ReferenceType in ('CASHINVOICE', 'INVOICE', 'INVOICEPAYMENT')
      then docs.OrgId || '-' || docs.TargetId
    else cast(null as string)
  end CustomerId
  , case
    when v.ReferenceType in ('SUPPLIERINVOICE', 'SUPPLIERPAYMENT')
      then docs.OrgId || '-' || docs.TargetId
    else cast(null as string)
  end SupplierId
  , r.Credit 
  , r.Debit
from {{ source('fortnox_api', 'vouchers') }} v
, unnest(VoucherRows) r
left join docs
  on docs.RefType = case
      when v.ReferenceType in ('CASHINVOICE', 'INVOICE', 'INVOICEPAYMENT') then 'INV'
      when v.ReferenceType in ('SUPPLIERINVOICE', 'SUPPLIERPAYMENT') then 'SUP'
      else cast(null as string)
    end
  and docs.OrgId = v.OrgId
  and docs.Id = v.ReferenceNumber
where r.removed is not true

  -- ReferenceType instructions:
  -- * ACCRUAL => reference number in description, leads to SupplierInvoices, CustomerInvoices, Vouchers (something else?)
  -- * CASHINVOICE => fact_invoices.InvoiceNo
  -- * INVOICE => fact_invoices.InvoiceNo
  -- * INVOICEPAYMENT => fact_invoices.InvoiceNo AND fact_invoice_payments.InvoiceNo, could be null for customer debt write-off
  -- * MANUAL => no references
  -- * RECEIPT => no references
  -- * SUPPLIERINVOICE => fact_supplier_invoices.SupplierInvoiceNo
  -- * SUPPLIERPAYMENT => fact_supplier_invoices.SupplierInvoiceNo, could be null for Levbet ()
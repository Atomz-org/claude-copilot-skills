{{ config(alias=model_alias(model.name), enabled = erp_sources_for('fact_invoice_payments') | length > 0) }}

{{ erp_union('fact_invoice_payments') }}

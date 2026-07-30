{{ config(alias=model_alias(model.name), enabled = erp_sources_for('fact_employee_wages') | length > 0) }}

{{ erp_union('fact_employee_wages') }}

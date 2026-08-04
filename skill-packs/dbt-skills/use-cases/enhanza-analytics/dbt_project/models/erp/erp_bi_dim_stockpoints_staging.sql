{{ config(alias=model_alias(model.name), enabled = erp_sources_for('dim_stockpoints') | length > 0) }}

{{ erp_union('dim_stockpoints') }}

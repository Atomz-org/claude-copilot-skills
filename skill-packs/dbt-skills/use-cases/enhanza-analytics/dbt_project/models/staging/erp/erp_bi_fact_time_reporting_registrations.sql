{{ config(materialized='ephemeral') }}

{{ erp_union('fact_time_reporting_registrations') }}

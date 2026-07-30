{{ config(materialized='ephemeral') }}

{{ erp_union('fact_attendance_transactions') }}

{{ config(
    alias='latest_source_sync',
    materialized='view'
) }}

{{ get_latest_source_timestamp() }}
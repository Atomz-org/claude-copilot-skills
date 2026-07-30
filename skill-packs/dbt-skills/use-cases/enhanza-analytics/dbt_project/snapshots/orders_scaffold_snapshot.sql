{% snapshot orders_scaffold_snapshot %}
{{
    config(
        target_schema=target.schema,
        unique_key='order_id',
        strategy='check',
        check_cols=['order_status']
    )
}}

select
    1001 as order_id,
    'paid' as order_status

{% endsnapshot %}

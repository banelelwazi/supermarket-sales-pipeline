with source as (
    select * from {{ source('raw', 'pos_transactions') }}
)

select
    transaction_id || '-' || line_number::text                      as sales_line_id,
    transaction_id,
    line_number,
    store_id,
    till_id,
    product_sku,
    quantity,
    unit_price,
    discount_amount,
    line_total,
    lower(payment_method)                                           as payment_method,
    sold_at,
    sold_at at time zone '{{ var("local_timezone") }}'              as sold_at_local,
    batch_hour,
    run_id,
    loaded_at
from source

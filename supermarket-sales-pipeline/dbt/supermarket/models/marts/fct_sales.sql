{#
  Incremental: each hourly run only processes rows loaded since the last build.
  Prices are VAT inclusive, so VAT is backed out of the line total using the
  product's rate (basic foods are zero rated in South Africa).
#}
{{
    config(
        materialized='incremental',
        unique_key='sales_line_id',
        incremental_strategy='delete+insert',
        on_schema_change='append_new_columns'
    )
}}

with sales as (
    select * from {{ ref('stg_pos_transactions') }}
    {% if is_incremental() %}
    where loaded_at > (select coalesce(max(loaded_at), '1900-01-01') from {{ this }})
    {% endif %}
),

products as (
    select product_sku, vat_rate from {{ ref('dim_product') }}
)

select
    s.sales_line_id,
    s.transaction_id,
    s.line_number,
    s.store_id,
    s.till_id,
    s.product_sku,
    s.payment_method,
    s.sold_at,
    s.sold_at_local,
    s.sold_at_local::date                                           as sales_date,
    extract(hour from s.sold_at_local)::int                         as sales_hour,
    s.quantity,
    s.unit_price,
    round(s.quantity * s.unit_price, 2)                             as gross_amount,
    s.discount_amount,
    s.line_total                                                    as net_amount,
    round(s.line_total * p.vat_rate / (1 + p.vat_rate), 2)          as vat_amount,
    s.line_total - round(s.line_total * p.vat_rate / (1 + p.vat_rate), 2)
                                                                    as net_amount_excl_vat,
    s.run_id,
    s.loaded_at
from sales s
left join products p on s.product_sku = p.product_sku

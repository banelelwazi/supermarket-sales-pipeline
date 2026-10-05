-- The table the operations team watches: how each store is trading, hour by hour.
select
    f.sales_date,
    f.sales_hour,
    f.store_id,
    s.store_name,
    s.city,
    count(distinct f.transaction_id)                                    as transactions,
    sum(f.quantity)                                                     as units_sold,
    sum(f.net_amount)                                                   as revenue,
    sum(f.discount_amount)                                              as discounts,
    sum(f.vat_amount)                                                   as vat,
    round(sum(f.net_amount) / nullif(count(distinct f.transaction_id), 0), 2)
                                                                        as avg_basket_value,
    round(
        100.0 * sum(case when f.payment_method = 'cash' then f.net_amount else 0 end)
        / nullif(sum(f.net_amount), 0), 1
    )                                                                   as cash_share_pct
from {{ ref('fct_sales') }} f
join {{ ref('dim_store') }} s on f.store_id = s.store_id
group by 1, 2, 3, 4, 5

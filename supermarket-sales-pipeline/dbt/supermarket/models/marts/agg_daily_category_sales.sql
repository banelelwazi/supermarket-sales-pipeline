-- Daily sales by product category, for buyers and merchandising.
select
    f.sales_date,
    p.category,
    count(distinct f.transaction_id)    as transactions,
    sum(f.quantity)                     as units_sold,
    sum(f.net_amount)                   as revenue,
    sum(f.discount_amount)              as discounts,
    sum(f.vat_amount)                   as vat
from {{ ref('fct_sales') }} f
join {{ ref('dim_product') }} p on f.product_sku = p.product_sku
group by 1, 2

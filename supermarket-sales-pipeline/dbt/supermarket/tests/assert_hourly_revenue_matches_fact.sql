-- The hourly summary must account for every rand in the fact table.
with fact as (
    select coalesce(sum(net_amount), 0) as revenue from {{ ref('fct_sales') }}
),

summary as (
    select coalesce(sum(revenue), 0) as revenue from {{ ref('agg_hourly_store_sales') }}
)

select fact.revenue as fact_revenue, summary.revenue as summary_revenue
from fact cross join summary
where abs(fact.revenue - summary.revenue) > 0.01

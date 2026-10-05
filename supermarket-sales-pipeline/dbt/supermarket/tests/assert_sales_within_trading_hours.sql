-- Sales outside a store's trading hours point to a clock or store mapping problem.
{{ config(severity='warn') }}

select f.sales_line_id, f.store_id, f.sold_at_local
from {{ ref('fct_sales') }} f
join {{ ref('dim_store') }} s on f.store_id = s.store_id
where f.sales_hour < s.opening_hour
   or f.sales_hour >= s.closing_hour

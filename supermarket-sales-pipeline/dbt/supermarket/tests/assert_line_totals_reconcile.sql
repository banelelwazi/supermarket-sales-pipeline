-- Every line must add up: quantity x price, less discount, equals what was paid.
select sales_line_id, gross_amount, discount_amount, net_amount
from {{ ref('fct_sales') }}
where abs(gross_amount - discount_amount - net_amount) > 0.01

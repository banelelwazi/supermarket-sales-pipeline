-- A sale in the future means a till clock is wrong or the data was tampered with.
select sales_line_id, sold_at
from {{ ref('fct_sales') }}
where sold_at > now() + interval '5 minutes'

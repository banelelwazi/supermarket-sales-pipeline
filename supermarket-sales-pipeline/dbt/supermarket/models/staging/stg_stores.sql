select
    store_id,
    store_name,
    city,
    province,
    store_size,
    opening_hour,
    closing_hour,
    closing_hour - opening_hour as trading_hours_per_day,
    till_count
from {{ ref('stores') }}

select
    product_sku,
    product_name,
    category,
    unit_price,
    vat_rate,
    vat_rate = 0 as is_zero_rated
from {{ ref('products') }}

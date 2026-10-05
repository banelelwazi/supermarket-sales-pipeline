# Data dictionary

Money is in South African rand. Prices on the till are VAT inclusive.

## Source export (`data/landing/sales_YYYYMMDDTHH00Z.csv`)

One file per UTC hour, one row per line on a till slip. Same columns as `raw.pos_transactions` below, from `transaction_id` to `sold_at`. `sold_at` is ISO 8601 with a UTC offset, for example `2026-10-05T13:24:10+00:00`. Hours when every store is closed still produce a file, with only the header row.

## raw.pos_transactions

Validated till lines, exactly as received. Written only by the Python loader.

| Column | Type | Description |
|---|---|---|
| `transaction_id` | text | Till slip id: store, local date and hour, basket number. `JHB01-2026100512-0004` |
| `line_number` | integer | Position of the line on the slip, from 1 |
| `store_id` | text | Store code, see `reference.stores` |
| `till_id` | text | Till the sale went through, `T01` to `T10` |
| `product_sku` | text | Product code, see `reference.products` |
| `quantity` | integer | Units sold, always above zero |
| `unit_price` | numeric(10,2) | Shelf price per unit, VAT inclusive |
| `discount_amount` | numeric(10,2) | Promotion discount on the line, 0 if none |
| `line_total` | numeric(10,2) | What the customer paid for the line: quantity x price less discount |
| `payment_method` | text | `card`, `cash` or `mobile_wallet` |
| `sold_at` | timestamptz | When the slip was rung up |
| `batch_hour` | timestamptz | The UTC hour this row was loaded as part of |
| `run_id` | uuid | Run that loaded it, see `audit.pipeline_runs` |
| `loaded_at` | timestamptz | When it was inserted. Drives the incremental fact table |

Primary key: `(transaction_id, line_number)`.

## raw.rejected_records

Rows that failed validation.

| Column | Type | Description |
|---|---|---|
| `rejected_id` | bigserial | Surrogate key |
| `batch_hour` | timestamptz | Hour the row came in with |
| `run_id` | uuid | Run that rejected it |
| `reject_reasons` | text | Every rule the row broke, separated by `;` |
| `raw_record` | jsonb | The row exactly as it arrived, all values as text |
| `rejected_at` | timestamptz | When it was quarantined |

## audit.pipeline_runs

One row per attempt at loading an hour.

| Column | Type | Description |
|---|---|---|
| `run_id` | uuid | Primary key |
| `batch_hour` | timestamptz | The UTC hour being loaded |
| `status` | text | `running`, `success`, `success_with_warnings` or `failed` |
| `rows_received` | integer | Rows in the export |
| `rows_loaded` | integer | New rows inserted. 0 on a rerun of an already loaded hour |
| `rows_rejected` | integer | Rows quarantined |
| `dbt_status` | text | `success` or `failed` for the dbt build that followed, blank if dbt was not needed |
| `error_message` | text | What went wrong, for failed runs |
| `started_at`, `finished_at` | timestamptz | Timing |

A `running` row that never finished means the process was killed mid run. The next `hourly` run will retry that hour because it has no successful run.

## reference.stores (seed)

| Column | Description |
|---|---|
| `store_id` | Store code |
| `store_name`, `city`, `province` | Where it is |
| `store_size` | `small`, `medium` or `large`. Drives simulated foot traffic |
| `opening_hour`, `closing_hour` | Trading hours in SAST, 24 hour clock. Open from opening up to (not including) closing |
| `till_count` | Number of tills |

## reference.products (seed)

| Column | Description |
|---|---|
| `product_sku` | Product code |
| `product_name`, `category` | What it is |
| `unit_price` | Current shelf price, VAT inclusive |
| `vat_rate` | `0.15`, or `0.00` for zero rated basic foods |

## marts.fct_sales

One row per line sold. Built incrementally.

| Column | Description |
|---|---|
| `sales_line_id` | `transaction_id` and `line_number` joined. Primary key |
| `transaction_id`, `line_number`, `store_id`, `till_id`, `product_sku`, `payment_method` | As in raw |
| `sold_at` | UTC timestamp |
| `sold_at_local` | SAST timestamp |
| `sales_date`, `sales_hour` | Trading date and hour in SAST |
| `quantity`, `unit_price`, `discount_amount` | As in raw |
| `gross_amount` | Quantity x price, before discount |
| `net_amount` | What the customer paid, VAT inclusive |
| `vat_amount` | VAT inside `net_amount` |
| `net_amount_excl_vat` | `net_amount` less VAT |
| `run_id`, `loaded_at` | Lineage back to the load |

## marts.dim_store, marts.dim_product

The reference seeds, plus `trading_hours_per_day` on stores and `is_zero_rated` on products.

## marts.agg_hourly_store_sales

One row per store per SAST hour.

| Column | Description |
|---|---|
| `sales_date`, `sales_hour`, `store_id`, `store_name`, `city` | Grain |
| `transactions` | Number of baskets |
| `units_sold` | Total units |
| `revenue` | Total paid, VAT inclusive |
| `discounts`, `vat` | Totals |
| `avg_basket_value` | Revenue / baskets |
| `cash_share_pct` | Share of revenue paid in cash. Useful for cash in transit planning |

## marts.agg_daily_category_sales

One row per category per SAST day, with `transactions`, `units_sold`, `revenue`, `discounts` and `vat`.

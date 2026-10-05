# Data quality

Quality is checked at two points. Each catches things the other can't.

## Gate 1: row validation in Python (before loading)

Every row in the export is checked by `pipeline/validate.py`. A row that breaks any rule goes to `raw.rejected_records` with every rule it broke, and its original values untouched. Rows that pass carry on to the warehouse.

| Rule | Catches | Example |
|---|---|---|
| `missing_or_malformed_field` | Blank values, or values that can't be read as the right type | `quantity = "abc"`, empty `product_sku` |
| `invalid_quantity` | Zero, negative or fractional quantities | `quantity = -2` |
| `unknown_store` | Store codes not in the stores reference | `XXX99` |
| `unknown_product` | SKUs not in the catalogue | `SKU-99999` |
| `price_mismatch` | Unit price different from the catalogue price | A till with an outdated price file |
| `invalid_discount` | Negative discounts, or discounts bigger than the line | `discount_amount = -5` |
| `line_total_mismatch` | Quantity x price minus discount doesn't equal the total | Rounding bugs, tampering |
| `invalid_payment_method` | Anything other than card, cash or mobile_wallet | `crypto` |
| `outside_batch_window` | Sale time not inside the hour being loaded | A till clock days out |
| `duplicate_line` | The same transaction and line number twice | A till resending lines |

Rules only judge values that are present, so one missing field is reported once, as `missing_or_malformed_field`, instead of setting off five other rules. Payment methods are trimmed and lower cased before checking, so `" CARD "` is fixed rather than rejected.

## Gate 2: dbt tests (after transforming)

`dbt build` runs these against the warehouse every time new data loads.

| Test | On | Checks |
|---|---|---|
| `unique`, `not_null` | Every primary key | No duplicate or missing keys in any model |
| `relationships` | `fct_sales.store_id`, `fct_sales.product_sku` | Every sale points at a real store and product |
| `accepted_values` | `payment_method`, `store_size`, `vat_rate` | Only expected categories |
| `positive_value` (custom) | Quantity, prices, amounts, revenue, basket value | No negative money or stock |
| `not_null` | `fct_sales.vat_amount` | Every product sold has a VAT rate |
| `assert_line_totals_reconcile` | `fct_sales` | Every line still adds up after modelling |
| `assert_no_future_sales` | `fct_sales` | Nothing dated in the future |
| `assert_hourly_revenue_matches_fact` | `agg_hourly_store_sales` | The summary accounts for every rand in the fact table |
| `assert_sales_within_trading_hours` (warn) | `fct_sales` | No sales recorded while a store is closed |

Some of these overlap with Gate 1 on purpose. If someone loads data another way, or a later code change breaks the validator, the warehouse tests still hold the line.

## Other checks

| Check | Where | Catches |
|---|---|---|
| Missing export | `extract.py` | The till system never delivered the hour's file |
| Schema check | `extract.py` | The export arrived with columns missing or renamed |
| Silent stores | `checks.py` | A store that was open but sent no sales at all |
| Unit and integration tests | `tests/` | Bugs in the pipeline code itself, run in CI on every push |

## Severity

| Situation | Severity | Effect |
|---|---|---|
| Some rows rejected, at or below 5% of the hour | WARNING | Email, run succeeds |
| More than 5% of rows rejected (`REJECT_RATE_CRITICAL_THRESHOLD`) | CRITICAL | Email, run fails |
| Open store sent nothing | WARNING | Email, run succeeds |
| Export missing or wrong columns | CRITICAL | Email, run fails, hour retried next run |
| Any dbt model or test fails | CRITICAL | Email, run fails |
| A dbt test set to warn fires | WARNING | Email, run succeeds |
| Database unreachable or unexpected error | CRITICAL | Email, run fails |

Everything from one run goes into a single message. Set `ALERT_MIN_SEVERITY=critical` to only be emailed about the serious things.

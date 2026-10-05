# Architecture

## Components

| Component | Tool | Job |
|---|---|---|
| Source | POS simulator (`pipeline/generator.py`) | Produces one CSV export per hour, like a till system would |
| Landing zone | `data/landing/` | Where exports arrive. Processed files move to `data/archive/YYYY/MM/DD/` |
| Ingestion | Python, pandas, psycopg2 | Extract, validate, load, quarantine |
| Warehouse | PostgreSQL 16 | Raw, staging, marts, reference and audit schemas |
| Transformation and tests | dbt | Builds the star schema and runs 35 data tests |
| Orchestration | `pipeline/run.py` | Decides which hours to load, runs every step, collects findings |
| Scheduling | GitHub Actions cron | Starts a run at five past every hour |
| Alerting | SMTP email, Slack webhook, health check ping | Tells people when something is wrong |

## Life of an hourly run

Say it is 14:05 UTC (16:05 in Johannesburg) and GitHub Actions starts the hourly workflow.

1. **`init-db`** makes sure the raw, quarantine and audit tables exist. It only ever creates things, so running it every time is safe.
2. **Find the work.** `hourly` reads `audit.pipeline_runs` and lists every complete hour in the last 24 without a successful run. Normally that is just 13:00 UTC. If the 11:00 run had failed because the export was late, 11:00 would be on the list too.
3. For each hour, oldest first:
   1. A row is added to `audit.pipeline_runs` with status `running`.
   2. With `SIMULATE_SOURCE=true`, the simulator writes `sales_20261005T1300Z.csv` to the landing zone.
   3. **Extract** reads the file with every column as text. A missing file or missing columns is a critical problem for that hour.
   4. **Validate** types the data and applies the 10 rules in [data_quality.md](data_quality.md).
   5. **Load** inserts good rows into `raw.pos_transactions` and replaces the hour's rows in `raw.rejected_records`. Both happen in one transaction.
   6. The file is archived and the audit row is closed with counts and a status.
   7. **Checks** look at the result: rejected rows, and stores that were open but sent nothing.
4. **dbt build** runs once for the whole run, but only if new rows were loaded. It refreshes the seeds, builds the models and runs every test.
5. **Report.** All findings are combined into one message and sent if they meet `ALERT_MIN_SEVERITY`.
6. **Exit.** Code 1 if anything was critical, which turns the GitHub Actions run red. Otherwise the optional health check URL is pinged.

One hour failing does not stop the others. Each hour is its own transaction with its own audit row.

## Warehouse layers

```
raw          written by Python only
  pos_transactions       validated till lines, exactly as received
  rejected_records       quarantined lines with reasons
audit
  pipeline_runs          one row per attempt at an hour
reference    dbt seeds
  stores, products
staging      dbt views, light cleaning
  stg_pos_transactions, stg_stores, stg_products
marts        dbt tables, what people query
  fct_sales                    one row per line sold (incremental)
  dim_store, dim_product
  agg_hourly_store_sales       store performance by hour
  agg_daily_category_sales     category performance by day
```

The split is deliberate. Python owns getting data in safely. dbt owns everything after that. Neither writes to the other's tables.

## Time zones

Stores trade on South African Standard Time (UTC+2, no daylight saving). The pipeline stores and schedules everything in UTC, because that is what GitHub Actions cron and Postgres `timestamptz` use. Local time only appears where it means something to people:

- the simulator and the silent store check use local time to know which stores are open
- `fct_sales.sold_at_local`, `sales_date` and `sales_hour` are in SAST, so reports line up with trading days

A sale at 00:30 SAST on the 26th happened at 22:30 UTC on the 25th, but it belongs in the 26th's trading figures. None of FreshWay's stores trade that late yet, but the day a 24 hour store opens, this matters. Getting it wrong is a classic source of "the numbers don't match the till" complaints.

## Idempotency

Every step can be repeated without changing the result:

| Step | How |
|---|---|
| Source | Each hour's simulated data is seeded from the hour itself |
| Raw load | Primary key on `(transaction_id, line_number)` with `ON CONFLICT DO NOTHING` |
| Quarantine | Rows for the hour are deleted and re-inserted |
| `fct_sales` | Incremental on `loaded_at`, merged on `sales_line_id` |
| Other marts | Rebuilt in full each run (they are small) |

This is what makes `backfill`, manual reruns and automatic catch-up safe.

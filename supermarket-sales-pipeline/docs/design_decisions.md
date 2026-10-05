# Design decisions

Why the pipeline is built the way it is, what I traded off, and what I would change at a bigger scale.

## 1. GitHub Actions for scheduling, not Airflow

**Decision:** a cron triggered GitHub Actions workflow.

**Why:** the job is one linear run per hour. Airflow would add a scheduler, a metadata database and a web server to keep running, for a DAG with one path. GitHub Actions is free for public repos, keeps logs and run history, and lives next to the code.

**Trade off:** cron on Actions can start late and has no built in backfill or retries. I covered that in the pipeline itself (see decision 2), so the scheduler only has to be roughly on time. The orchestrator is a plain CLI, so moving to Airflow, Dagster or a server cron later means changing one line of scheduling, not the pipeline.

## 2. The pipeline decides what to load, not the scheduler

**Decision:** each run loads every hour in the last 24 that has no successful entry in `audit.pipeline_runs`, instead of only "the previous hour".

**Why:** schedulers skip runs, exports arrive late, databases blip. With "previous hour only", every one of those leaves a permanent gap that someone has to notice and backfill by hand. With this approach, gaps close on their own next run.

**Trade off:** the first run after a long outage does more work. The lookback is capped (`LOOKBACK_HOURS`) so a long outage can't turn into a huge run, and `backfill` covers anything older.

## 3. Validate in Python before loading, and test again in dbt

**Decision:** two quality gates.

**Why:** they answer different questions. The Python validator asks "is this row believable?" and can stop a bad row before it lands, keeping it for investigation. dbt tests ask "is the warehouse correct as a whole?": unique keys, relationships between tables, summaries that reconcile with the detail. Neither can do the other's job well. The overlap is intentional too. If data ever gets in another way, the warehouse tests still catch it.

**Trade off:** some rules live in two places. I kept the store and product lists in one place (the dbt seeds, read by both) so the most likely thing to drift can't.

## 4. Quarantine bad rows, don't drop them or fail the whole hour

**Decision:** bad rows go to `raw.rejected_records` with their original values and every reason they failed. Good rows from the same hour still load.

**Why:** one faulty till shouldn't hide the sales from five healthy stores. Head office still sees the hour. Meanwhile nothing is lost, and the reasons point straight at the cause.

**Trade off:** the hour's totals are incomplete until the bad rows are fixed and reloaded. The alert says exactly how many rows are missing, so nobody mistakes an incomplete hour for a quiet one.

## 5. Make every step idempotent

**Decision:** natural primary key with `ON CONFLICT DO NOTHING`, delete and replace for quarantine, incremental dbt model on `loaded_at`, and a seeded simulator.

**Why:** retries, catch-up and backfills all depend on "run it again" being safe. Without this, every rerun is a risk of double counting revenue.

**Trade off:** `DO NOTHING` means a corrected version of an already loaded line is ignored. In this domain a till line shouldn't change after the sale (a refund is a new transaction), so that is the right behaviour. If corrections were normal, I'd switch to `DO UPDATE` and track versions.

## 6. One alert per run, with severity levels

**Decision:** findings from a run are collected and sent as one message. Each finding is INFO, WARNING or CRITICAL, and only CRITICAL fails the run.

**Why:** the brief asks for an alert when there are errors in the data, but an alert per problem per hour trains people to ignore the inbox. One summary per run, with the worst problem first, is easier to act on. Failing the run only on critical problems keeps the GitHub Actions history meaningful.

**Trade off:** a small number of bad rows still produces an email. `ALERT_MIN_SEVERITY=critical` turns those off for teams that only want to hear about serious problems.

## 7. One config, through standard environment variables

**Decision:** the database connection uses the standard `PG*` variables, which psycopg2 and the dbt profile both read.

**Why:** no connection string to keep in sync between Python and dbt, and secrets come from the environment, never from the code.

## 8. A simulator as the source

**Decision:** a built in POS simulator instead of a static sample file.

**Why:** a pipeline that runs every hour needs new data every hour. A simulator also lets me produce the failures the pipeline exists to handle (faulty tills, outages) on demand, which is how CI proves that bad data really does fail the run. It is seeded by hour, so it behaves like a real source that always returns the same export for the same hour.

## What I would add next

- **Real source integration.** Read exports from object storage or SFTP instead of the simulator, with the landing zone in a bucket.
- **Scoped dbt tests.** Tests currently scan the whole fact table. At larger volumes I'd limit most of them to recently loaded data with a `where` config.
- **Partitioning.** Partition `raw.pos_transactions` and `fct_sales` by month once the tables get large.
- **Anomaly checks.** Compare each store's hour to the same hour on recent weeks and warn on big drops, which catches problems that pass every rule (for example a till that stops scanning one category).
- **A dashboard.** Point Power BI or Metabase at the marts schema for the operations team.
- **Data contracts.** Agree the export schema formally with the POS vendor and version it.

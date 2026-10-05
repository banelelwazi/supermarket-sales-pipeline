# Runbook

## Deploying the hourly schedule

The hourly workflow needs a Postgres it can reach from the internet, and somewhere to send emails.

### 1. Create a hosted Postgres

Any Postgres 14+ works. Neon and Supabase both have free tiers that are plenty for this. Create a database and note the host, port, user, password and database name. Hosted providers need SSL, which the workflow already sets with `PGSSLMODE=require`.

At roughly 9,000 rows a day the raw table grows by about 270,000 rows a month, so a free tier lasts a good while. Delete old archived hours if you get close to the limit.

### 2. Set up email

For Gmail: turn on 2 step verification, then create an App Password under your Google account's security settings. Use that 16 character password as `SMTP_PASSWORD`, never your normal password.

### 3. Add repository secrets

In GitHub: **Settings > Secrets and variables > Actions > New repository secret**.

| Secret | Example |
|---|---|
| `PGHOST` | `ep-quiet-sun-123456.eu-central-1.aws.neon.tech` |
| `PGPORT` | `5432` |
| `PGUSER` | `neondb_owner` |
| `PGPASSWORD` | your database password |
| `PGDATABASE` | `supermarket` |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `you@gmail.com` |
| `SMTP_PASSWORD` | the App Password |
| `ALERT_EMAIL_FROM` | `you@gmail.com` |
| `ALERT_EMAIL_TO` | `team@example.com,you@gmail.com` |
| `SLACK_WEBHOOK_URL` | optional |
| `HEALTHCHECK_URL` | optional, see below |

### 4. Run it once by hand

**Actions > Hourly sales pipeline > Run workflow**, leaving the hour empty. The first run finds no history, so it loads the last 24 hours in one go. After that the schedule takes over.

### 5. Optional: a dead man's switch

If the scheduler itself stops, nothing runs, so nothing sends an alert. To cover that, create a free check on a service like healthchecks.io with a 1 hour period and a grace time, and put its ping URL in `HEALTHCHECK_URL`. The pipeline pings it after every healthy run. If the pings stop, that service emails you.

### Things to know about GitHub Actions cron

- Scheduled runs can start late when GitHub is busy, sometimes by 10 to 30 minutes. That is fine here: the pipeline loads whatever hours are missing, whenever it runs.
- In public repositories, scheduled workflows are switched off after 60 days with no activity in the repo. A commit or a manual run turns them back on.

## When an alert fires

Every alert email lists the hour, what was found, and the counts for each hour in the run.

### "N of M rows rejected"

The validator quarantined rows. Find out which store and which rules:

```sql
select raw_record->>'store_id' as store,
       raw_record->>'till_id'  as till,
       reject_reasons,
       count(*)
from raw.rejected_records
where batch_hour = '2026-09-26 09:00+00'
group by 1, 2, 3
order by 4 desc;
```

Then look at what was actually sent:

```sql
select reject_reasons, raw_record
from raw.rejected_records
where batch_hour = '2026-09-26 09:00+00'
limit 20;
```

Common causes:

| Reasons | Likely cause | Action |
|---|---|---|
| Mostly from one till | Faulty till or till software | Ask the store to restart or swap the till |
| `price_mismatch` across a store | Store has an old price file | Push the current price file to the store |
| `unknown_product` | New product sold before it was added to the catalogue | Add it to `seeds/products.csv` and reload the hour |
| `outside_batch_window` | Till clock is wrong | Fix the clock |
| `duplicate_line` | Till resent lines after a network drop | Usually harmless, the first copy was loaded |

Once the cause is fixed and corrected data is in the landing zone, reload the hour:

```bash
python -m pipeline batch --hour 2026-09-26T09:00
```

Good rows that were already loaded are skipped, newly valid rows are added, and the quarantine for that hour is replaced.

### "No sales received from N open store(s)"

A store was open but sent nothing. Usually the store's till system or network is down. Call the store. When the data is resent, reload the hour as above.

### "POS export problem"

The hour's file never arrived, or arrived with the wrong columns. Nothing was loaded for that hour. Once the file lands, you don't need to do anything: the next hourly run sees the hour has no successful load and picks it up, as long as it is within the 24 hour lookback.

### "dbt build or data tests failed"

The data loaded, but something downstream is wrong. The email lists the failing models or tests. To see the failing rows:

```bash
cd dbt/supermarket
dbt test --select <test_name> --store-failures --profiles-dir .
```

The GitHub Actions run also keeps `run_results.json` as an artifact for 7 days.

### "Pipeline could not run"

Usually the database is unreachable or credentials changed. Check the database is up and the secrets are right, then run the workflow by hand. Missed hours are caught up automatically.

## Useful queries

Run history for today:

```sql
select batch_hour, status, rows_received, rows_loaded, rows_rejected, dbt_status, error_message
from audit.pipeline_runs
where started_at >= current_date
order by started_at desc;
```

Hours in the last day with no successful load:

```sql
select hour
from generate_series(date_trunc('hour', now()) - interval '24 hours',
                     date_trunc('hour', now()) - interval '1 hour',
                     interval '1 hour') as hour
where hour not in (
    select batch_hour from audit.pipeline_runs
    where status in ('success', 'success_with_warnings')
);
```

Today's trading so far, by store:

```sql
select store_name, sum(transactions) as baskets, sum(revenue) as revenue
from marts.agg_hourly_store_sales
where sales_date = (now() at time zone 'Africa/Johannesburg')::date
group by store_name
order by revenue desc;
```

## Backfilling

Load any range of hours (up to 31 days per command):

```bash
python -m pipeline backfill --start 2026-09-01T00:00 --end 2026-09-30T23:00
```

Hours that are already loaded are skipped at the row level, so overlapping ranges are safe.

-- Landing tables owned by the Python loader. dbt builds everything downstream.
-- Safe to run on every deploy: nothing here drops or changes existing data.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS audit;

-- One row per line on a till slip, exactly as the POS reported it (after validation).
CREATE TABLE IF NOT EXISTS raw.pos_transactions (
    transaction_id   TEXT           NOT NULL,
    line_number      INTEGER        NOT NULL,
    store_id         TEXT           NOT NULL,
    till_id          TEXT           NOT NULL,
    product_sku      TEXT           NOT NULL,
    quantity         INTEGER        NOT NULL,
    unit_price       NUMERIC(10, 2) NOT NULL,
    discount_amount  NUMERIC(10, 2) NOT NULL,
    line_total       NUMERIC(10, 2) NOT NULL,
    payment_method   TEXT           NOT NULL,
    sold_at          TIMESTAMPTZ    NOT NULL,
    batch_hour       TIMESTAMPTZ    NOT NULL,
    run_id           UUID           NOT NULL,
    loaded_at        TIMESTAMPTZ    NOT NULL DEFAULT now(),
    PRIMARY KEY (transaction_id, line_number)
);

CREATE INDEX IF NOT EXISTS ix_pos_transactions_loaded_at ON raw.pos_transactions (loaded_at);
CREATE INDEX IF NOT EXISTS ix_pos_transactions_batch_hour ON raw.pos_transactions (batch_hour);

-- Quarantine. Rows that failed validation are kept here, untouched, with the reasons.
CREATE TABLE IF NOT EXISTS raw.rejected_records (
    rejected_id     BIGSERIAL   PRIMARY KEY,
    batch_hour      TIMESTAMPTZ NOT NULL,
    run_id          UUID        NOT NULL,
    reject_reasons  TEXT        NOT NULL,
    raw_record      JSONB       NOT NULL,
    rejected_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_rejected_records_batch_hour ON raw.rejected_records (batch_hour);

-- One row per attempt at processing an hour. This is how the pipeline knows
-- which hours still need loading, and how a person can see its history.
CREATE TABLE IF NOT EXISTS audit.pipeline_runs (
    run_id          UUID        PRIMARY KEY,
    batch_hour      TIMESTAMPTZ NOT NULL,
    status          TEXT        NOT NULL
        CHECK (status IN ('running', 'success', 'success_with_warnings', 'failed')),
    rows_received   INTEGER,
    rows_loaded     INTEGER,
    rows_rejected   INTEGER,
    dbt_status      TEXT,
    error_message   TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_pipeline_runs_batch_hour ON audit.pipeline_runs (batch_hour);

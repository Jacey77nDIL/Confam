-- Run against your Confam PostgreSQL database once (idempotent).
-- Fixes: UndefinedColumn on saved_recipients (account_name, aliases, usage_frequency, last_used).
-- Prefer ``ensure_saved_recipients_orm_columns.sql`` for one combined script.

ALTER TABLE saved_recipients
  ADD COLUMN IF NOT EXISTS account_name VARCHAR(255);

ALTER TABLE saved_recipients
  ADD COLUMN IF NOT EXISTS aliases JSONB;

ALTER TABLE saved_recipients
  ADD COLUMN IF NOT EXISTS usage_frequency INTEGER NOT NULL DEFAULT 0;

ALTER TABLE saved_recipients
  ADD COLUMN IF NOT EXISTS last_used TIMESTAMPTZ;

-- Optional: backfill account_name from legacy display_name where missing
UPDATE saved_recipients
SET account_name = display_name
WHERE account_name IS NULL AND display_name IS NOT NULL;

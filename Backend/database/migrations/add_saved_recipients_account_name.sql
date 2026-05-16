-- Explicit SQL (PostgreSQL) — run if ``account_name`` is missing from ``saved_recipients``:
--
--     ALTER TABLE saved_recipients ADD COLUMN account_name VARCHAR;
--
-- Idempotent default for this repo:
ALTER TABLE saved_recipients ADD COLUMN IF NOT EXISTS account_name VARCHAR(255);
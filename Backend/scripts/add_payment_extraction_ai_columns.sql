-- Idempotent migration: payment_extractions AI columns + uploaded_file FK.
-- Run once, e.g.:
--   psql "postgresql://USER:PASS@HOST:5432/DBNAME" -f backend/scripts/add_payment_extraction_ai_columns.sql
--
-- Uses DO blocks so PostgreSQL versions without "ADD COLUMN IF NOT EXISTS" still work.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'payment_extractions' AND column_name = 'uploaded_file_id'
  ) THEN
    ALTER TABLE payment_extractions
      ADD COLUMN uploaded_file_id INTEGER REFERENCES uploaded_files (id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'payment_extractions' AND column_name = 'raw_ai_response'
  ) THEN
    ALTER TABLE payment_extractions ADD COLUMN raw_ai_response TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'payment_extractions' AND column_name = 'parsed_json'
  ) THEN
    ALTER TABLE payment_extractions ADD COLUMN parsed_json JSONB;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_payment_extractions_uploaded_file_id ON payment_extractions (uploaded_file_id);

-- Add Money Sending Mode payload column on messages (assistant replies).
-- Run once, e.g. psql "$DATABASE_URL" -f backend/scripts/add_message_payment_metadata.sql
--
-- Plain one-liner (only if the column is missing; errors if it already exists):
--   ALTER TABLE messages ADD COLUMN payment_metadata JSONB;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'messages' AND column_name = 'payment_metadata'
  ) THEN
    ALTER TABLE messages ADD COLUMN payment_metadata JSONB;
  END IF;
END $$;

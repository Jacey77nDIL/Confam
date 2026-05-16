-- Align physical table ``saved_recipients`` with ``models.saved_recipient.SavedRecipient``.
-- Safe to re-run (PostgreSQL IF NOT EXISTS).

ALTER TABLE saved_recipients ADD COLUMN IF NOT EXISTS bank_name VARCHAR(255);
ALTER TABLE saved_recipients ADD COLUMN IF NOT EXISTS account_name VARCHAR(255);
ALTER TABLE saved_recipients ADD COLUMN IF NOT EXISTS aliases JSONB;
ALTER TABLE saved_recipients ADD COLUMN IF NOT EXISTS usage_frequency INTEGER NOT NULL DEFAULT 0;
ALTER TABLE saved_recipients ADD COLUMN IF NOT EXISTS last_used TIMESTAMPTZ;

-- Optional: copy display_name into account_name where the new column is empty
UPDATE saved_recipients
SET account_name = display_name
WHERE account_name IS NULL AND display_name IS NOT NULL;

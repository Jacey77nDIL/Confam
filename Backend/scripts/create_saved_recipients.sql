-- Optional: idempotent table for saved bank recipients (also created via SQLAlchemy Base.metadata.create_all).

CREATE TABLE IF NOT EXISTS saved_recipients (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  display_name VARCHAR(255) NOT NULL,
  account_number VARCHAR(32) NOT NULL,
  bank_name VARCHAR(255),
  account_name VARCHAR(255),
  aliases JSONB,
  usage_frequency INTEGER NOT NULL DEFAULT 0,
  last_used TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_saved_recipient_user_account UNIQUE (user_id, account_number)
);

CREATE INDEX IF NOT EXISTS ix_saved_recipients_user_id ON saved_recipients (user_id);

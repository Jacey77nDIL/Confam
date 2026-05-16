-- WhatsApp Cloud API + optional user phone for auto-linking.
-- psql "$DATABASE_URL" -f database/migrations/add_whatsapp_cloud.sql

ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_e164 VARCHAR(32);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_phone_e164 ON users (phone_e164) WHERE phone_e164 IS NOT NULL;

CREATE TABLE IF NOT EXISTS whatsapp_sessions (
    id SERIAL PRIMARY KEY,
    user_phone VARCHAR(32) NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    chat_session_id INTEGER NOT NULL REFERENCES chat_sessions (id) ON DELETE CASCADE,
    linked_user_id INTEGER REFERENCES users (id) ON DELETE SET NULL,
    auth_pending_email VARCHAR(255),
    last_active TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_whatsapp_sessions_user_phone ON whatsapp_sessions (user_phone);

CREATE TABLE IF NOT EXISTS whatsapp_inbound_dedupe (
    id SERIAL PRIMARY KEY,
    wa_message_id VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_whatsapp_inbound_dedupe_msg ON whatsapp_inbound_dedupe (wa_message_id);

-- WhatsApp sign-in flow (email + password before chat).
-- psql "$DATABASE_URL" -f database/migrations/add_whatsapp_auth.sql

ALTER TABLE whatsapp_sessions ADD COLUMN IF NOT EXISTS auth_pending_email VARCHAR(255);

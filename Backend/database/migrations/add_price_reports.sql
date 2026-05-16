-- Market price reports for ML-driven QUERY / SUBMIT_PRICE flows.
-- psql "$DATABASE_URL" -f database/migrations/add_price_reports.sql

CREATE TABLE IF NOT EXISTS price_reports (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users (id) ON DELETE SET NULL,
    raw_message TEXT NOT NULL,
    normalized_message TEXT,
    product VARCHAR(128) NOT NULL,
    location VARCHAR(128) NOT NULL,
    unit VARCHAR(64),
    quantity DOUBLE PRECISION,
    price DOUBLE PRECISION NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    source VARCHAR(32) NOT NULL DEFAULT 'web',
    extracted_by VARCHAR(32) NOT NULL DEFAULT 'ml',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_price_reports_product ON price_reports (product);
CREATE INDEX IF NOT EXISTS ix_price_reports_location ON price_reports (location);
CREATE INDEX IF NOT EXISTS ix_price_reports_created_at ON price_reports (created_at);
CREATE INDEX IF NOT EXISTS ix_price_reports_product_location ON price_reports (product, location);

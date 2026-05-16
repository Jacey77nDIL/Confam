-- Track whether a price row came from ML or rule-based / hybrid extraction.
-- psql "$DATABASE_URL" -f database/migrations/add_price_reports_extracted_by.sql

ALTER TABLE price_reports
ADD COLUMN IF NOT EXISTS extracted_by VARCHAR(32) NOT NULL DEFAULT 'ml';

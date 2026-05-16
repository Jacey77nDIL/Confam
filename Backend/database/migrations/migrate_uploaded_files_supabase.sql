-- Migrate uploaded_files from local stored_name to Supabase-oriented columns.
-- Run after deploying code that expects storage_path (e.g. psql "$DATABASE_URL" -f ...).

ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS storage_path VARCHAR(1024);
ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS bucket_name VARCHAR(255);
ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS public_url VARCHAR(2048);
ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS file_type VARCHAR(32);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'uploaded_files' AND column_name = 'stored_name'
  ) THEN
    UPDATE uploaded_files SET
      storage_path = COALESCE(NULLIF(btrim(storage_path), ''), 'legacy-local/' || stored_name),
      bucket_name = COALESCE(NULLIF(btrim(bucket_name), ''), 'deprecated'),
      file_type = COALESCE(NULLIF(btrim(file_type), ''), 'unknown')
    WHERE storage_path IS NULL OR btrim(storage_path) = '';
    ALTER TABLE uploaded_files DROP COLUMN stored_name;
  END IF;
END $$;

ALTER TABLE uploaded_files ALTER COLUMN storage_path SET NOT NULL;
ALTER TABLE uploaded_files ALTER COLUMN bucket_name SET NOT NULL;
ALTER TABLE uploaded_files ALTER COLUMN file_type SET NOT NULL;

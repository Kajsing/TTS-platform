ALTER TABLE reader_export_jobs
ADD COLUMN audio_format TEXT NOT NULL DEFAULT 'wav'
CHECK (audio_format IN ('wav', 'mp3'));

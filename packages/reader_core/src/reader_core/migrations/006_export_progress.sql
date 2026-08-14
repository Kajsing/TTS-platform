ALTER TABLE reader_export_jobs
ADD COLUMN progress_phase TEXT NOT NULL DEFAULT 'queued'
CHECK (progress_phase IN (
    'queued', 'preparing', 'synthesizing', 'encoding',
    'finalizing', 'completed', 'failed', 'cancelled'
));

ALTER TABLE reader_export_jobs
ADD COLUMN progress_percent INTEGER NOT NULL DEFAULT 0
CHECK (progress_percent BETWEEN 0 AND 100);

UPDATE reader_export_jobs
SET progress_phase = CASE
        WHEN status = 'running' THEN 'preparing'
        ELSE status
    END,
    progress_percent = CASE WHEN status = 'completed' THEN 100 ELSE 0 END;

-- Phase 8 App: pipeline run log
-- One row per backfill or delta file the OFF job processes. History that
-- can't be regenerated, so CREATE TABLE IF NOT EXISTS, never DROP.
-- data_through = how current foods_source is after this run; the job uses
-- it to detect gaps (laptop off longer than OFF keeps delta files).
-- @author Tony Shin <tonyshin4065@gmail.com>

CREATE TABLE IF NOT EXISTS pipeline_runs (
	id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
	source       TEXT NOT NULL,                 -- 'off' (later 'usda')
	run_type     TEXT NOT NULL,                 -- 'backfill' or 'delta'
	run_date     DATE NOT NULL DEFAULT current_date,
	file_name    TEXT,                          -- delta file name or dump URL
	rows_read    INTEGER,                       -- JSON lines read
	rows_loaded  INTEGER,                       -- rows inserted or changed
	status       TEXT NOT NULL,                 -- 'running', 'success', 'failed'
	note         TEXT,                          -- warnings (e.g. gap detected)
	error        TEXT,
	data_through TIMESTAMPTZ,
	started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
	finished_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_source_status
	ON pipeline_runs (source, status);

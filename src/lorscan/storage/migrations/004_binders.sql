CREATE TABLE binders (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  set_code    TEXT REFERENCES sets(set_code),
  finish      TEXT,
  notes       TEXT,
  created_at  TEXT NOT NULL
);

ALTER TABLE scans ADD COLUMN binder_id    INTEGER REFERENCES binders(id);
ALTER TABLE scans ADD COLUMN page_number  INTEGER;

ALTER TABLE scan_results ADD COLUMN position_anomaly             TEXT;
ALTER TABLE scan_results ADD COLUMN position_anomaly_detail      TEXT;
ALTER TABLE scan_results ADD COLUMN position_anomaly_resolved_at TEXT;

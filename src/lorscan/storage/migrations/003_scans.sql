CREATE TABLE scans (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  photo_hash            TEXT NOT NULL UNIQUE,
  photo_path            TEXT NOT NULL,
  status                TEXT NOT NULL,
  error_message         TEXT,
  api_request_payload   TEXT,
  api_response_payload  TEXT,
  cost_usd              REAL,
  created_at            TEXT NOT NULL,
  completed_at          TEXT
);
CREATE INDEX scans_status_idx     ON scans(status);
CREATE INDEX scans_created_at_idx ON scans(created_at);

CREATE TABLE scan_results (
  id                       INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id                  INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  grid_position            TEXT NOT NULL,
  claude_name              TEXT,
  claude_subtitle          TEXT,
  claude_collector_number  TEXT,
  claude_set_hint          TEXT,
  claude_ink_color         TEXT,
  claude_finish            TEXT,
  confidence               TEXT NOT NULL,
  matched_card_id          TEXT REFERENCES cards(card_id),
  match_method             TEXT,
  user_decision            TEXT,
  user_replaced_card_id    TEXT REFERENCES cards(card_id),
  applied_at               TEXT
);
CREATE INDEX scan_results_scan_idx ON scan_results(scan_id);

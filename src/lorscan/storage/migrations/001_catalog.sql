CREATE TABLE IF NOT EXISTS schema_migrations (
  version    TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE sets (
  set_code     TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  released_on  TEXT,
  total_cards  INTEGER NOT NULL,
  icon_url     TEXT,
  synced_at    TEXT NOT NULL
);

CREATE TABLE cards (
  card_id          TEXT PRIMARY KEY,
  set_code         TEXT NOT NULL REFERENCES sets(set_code),
  collector_number TEXT NOT NULL,
  name             TEXT NOT NULL,
  subtitle         TEXT,
  rarity           TEXT NOT NULL,
  ink_color        TEXT,
  cost             INTEGER,
  inkable          INTEGER,
  card_type        TEXT,
  body_text        TEXT,
  image_url        TEXT,
  api_payload      TEXT NOT NULL,
  UNIQUE(set_code, collector_number)
);
CREATE INDEX cards_name_idx ON cards(name);
CREATE INDEX cards_set_idx  ON cards(set_code);

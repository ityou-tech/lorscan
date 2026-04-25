CREATE TABLE collection_items (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id       TEXT NOT NULL REFERENCES cards(card_id),
  finish        TEXT NOT NULL DEFAULT 'regular',
  finish_label  TEXT,
  quantity      INTEGER NOT NULL DEFAULT 1,
  notes         TEXT,
  updated_at    TEXT NOT NULL,
  UNIQUE(card_id, finish, COALESCE(finish_label, ''))
);
CREATE INDEX collection_items_card_idx ON collection_items(card_id);

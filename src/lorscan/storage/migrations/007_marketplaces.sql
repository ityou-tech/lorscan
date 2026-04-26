CREATE TABLE marketplaces (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  slug         TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  base_url     TEXT NOT NULL,
  enabled      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE marketplace_set_categories (
  marketplace_id INTEGER NOT NULL REFERENCES marketplaces(id),
  set_code       TEXT NOT NULL REFERENCES sets(set_code),
  category_id    TEXT NOT NULL,
  category_path  TEXT NOT NULL,
  PRIMARY KEY (marketplace_id, set_code)
);

CREATE TABLE marketplace_listings (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  marketplace_id  INTEGER NOT NULL REFERENCES marketplaces(id),
  external_id     TEXT NOT NULL,
  card_id         TEXT REFERENCES cards(card_id),
  finish          TEXT,
  price_cents     INTEGER NOT NULL,
  currency        TEXT NOT NULL DEFAULT 'EUR',
  in_stock        INTEGER NOT NULL DEFAULT 0,
  url             TEXT NOT NULL,
  title           TEXT NOT NULL,
  fetched_at      TEXT NOT NULL,
  UNIQUE (marketplace_id, external_id)
);
CREATE INDEX idx_listings_card_stock
  ON marketplace_listings (card_id, in_stock, price_cents);

CREATE TABLE marketplace_sweeps (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  marketplace_id   INTEGER NOT NULL REFERENCES marketplaces(id),
  started_at       TEXT NOT NULL,
  finished_at      TEXT,
  listings_seen    INTEGER NOT NULL DEFAULT 0,
  listings_matched INTEGER NOT NULL DEFAULT 0,
  errors           INTEGER NOT NULL DEFAULT 0,
  status           TEXT NOT NULL
);

INSERT INTO marketplaces (slug, display_name, base_url, enabled)
VALUES ('bazaarofmagic', 'Bazaar of Magic', 'https://www.bazaarofmagic.eu', 1);

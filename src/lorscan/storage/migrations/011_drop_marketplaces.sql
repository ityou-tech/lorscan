-- Marketplace scraping (Bazaar of Magic adapter + sweeps) removed.
-- Buy-link URLs on the cards table (cardmarket_url, cardtrader_url) remain;
-- those live in 008_external_links.sql and back the CM/CT pocket icons.
DROP TABLE IF EXISTS marketplace_listings;
DROP TABLE IF EXISTS marketplace_set_categories;
DROP TABLE IF EXISTS marketplace_sweeps;
DROP TABLE IF EXISTS marketplaces;

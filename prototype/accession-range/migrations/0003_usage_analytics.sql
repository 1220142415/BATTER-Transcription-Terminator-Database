-- Page-view aggregates only; no raw IPs, user agents, or visitor identifiers.
CREATE TABLE IF NOT EXISTS analytics_daily_geo (
  day TEXT NOT NULL,
  country_code TEXT NOT NULL,
  region TEXT NOT NULL DEFAULT '',
  city TEXT NOT NULL DEFAULT '',
  views INTEGER NOT NULL DEFAULT 0 CHECK (views >= 0),
  PRIMARY KEY (day, country_code, region, city)
);

CREATE TABLE IF NOT EXISTS analytics_daily_path (
  day TEXT NOT NULL,
  path TEXT NOT NULL,
  views INTEGER NOT NULL DEFAULT 0 CHECK (views >= 0),
  PRIMARY KEY (day, path)
);

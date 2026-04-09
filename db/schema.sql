
DROP TABLE IF EXISTS network_events;

CREATE TABLE network_events (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  srcip      TEXT,
  dstip      TEXT,
  proto      TEXT,
  service    TEXT,
  sbytes     BIGINT,
  attack_cat TEXT,
  label      TEXT
);


-- docker compose -f infra\docker-compose.yml exec api python /db/seed.py --data /data/UNSW-NB15.csv --features /data/UNSW-NB15_features.csv --dsn postgresql://analyst_user:secure_password_123@db:5432/threat_hunting_db


CREATE TABLE jobs (
    job_id UUID PRIMARY KEY,
    status TEXT NOT NULL,          -- pending, processing, completed, failed
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    result_path TEXT,
    error_message TEXT
);

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'analyst', -- 'admin', 'analyst'
    is_active BOOLEAN DEFAULT TRUE
);

-- Seed dev-only users — NEVER use these credentials in production.
-- Rotate via: UPDATE users SET hashed_password = crypt('...', gen_salt('bf')) WHERE username = '...';
-- Hash generated with passlib bcrypt rounds=12 for: Hunt3r$2026!
INSERT INTO users (username, hashed_password, role) VALUES
('admin',   '$2b$12$vzMAkRhxWKw/vx1iDQxMQuKaOVOt4aqZZ9WbQvp6mN3dzMkRhZ/EO', 'admin'),
('analyst', '$2b$12$vzMAkRhxWKw/vx1iDQxMQuKaOVOt4aqZZ9WbQvp6mN3dzMkRhZ/EO', 'analyst');

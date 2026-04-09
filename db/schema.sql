
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

-- Seed Initial Users (Password: admin123 / admin123)
-- Hash generated via passlib
INSERT INTO users (username, hashed_password, role) VALUES 
('admin', '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW', 'admin'),
('analyst', '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW', 'analyst');

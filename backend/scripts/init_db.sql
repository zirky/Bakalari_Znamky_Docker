-- Inicializační·°skript pro SQLite databáº£i

-- auth_users
CREATE TABLE IF NOT EXISTS auth_users (
    id INTEGER PRIMARY KEY,
    role VARCHAR(20) NOT NULL UNIQUE,
    pin_hash VARCHAR(255) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_auth_users_role ON auth_users(role);

-- sessions
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    token VARCHAR(255) NOT NULL UNIQUE,
    user_id INTEGER NOT NULL,
    expires_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY(user_id) REFERENCES auth_users(id) ON DELETE CASCADE
);

-- app_settings
CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY,
    key VARCHAR(255) NOT NULL UNIQUE,
    value TEXT
);

-- sync_states
CREATE TABLE IF NOT EXISTS sync_states (
    id INTEGER PRIMARY KEY,
    sync_status VARCHAR(50) NOT NULL DEFAULT 'never',
    last_sync_at DATETIME,
    next_sync_at DATETIME,
    sync_started_at DATETIME,
    sync_from_date DATE,
    last_sync_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    running_balance_czk INTEGER NOT NULL DEFAULT 0,
    last_payout_at DATETIME
);

-- sync_runs
CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY,
    mode VARCHAR(50) NOT NULL,
    from_date DATE NOT NULL,
    status VARCHAR(50) NOT NULL,
    grades_found INTEGER NOT NULL DEFAULT 0,
    grades_new INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at DATETIME,
    finished_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- grades
CREATE TABLE IF NOT EXISTS grades (
    id INTEGER PRIMARY KEY,
    external_id VARCHAR(255) NOT NULL UNIQUE,
    subject VARCHAR(255) NOT NULL,
    grade_value VARCHAR(10) NOT NULL,
    grade_date DATE NOT NULL,
    description TEXT,
    school_year VARCHAR(20),
    source VARCHAR(50) NOT NULL DEFAULT 'bakalari',
    active_in_sync BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- reward_rules
CREATE TABLE IF NOT EXISTS reward_rules (
    id INTEGER PRIMARY KEY,
    grade_value VARCHAR(10) NOT NULL UNIQUE,
    reward_czk INTEGER NOT NULL,
    active BOOLEAN NOT NULL DEFAULT 1
);

-- rewards
CREATE TABLE IF NOT EXISTS rewards (
    id INTEGER PRIMARY KEY,
    grade_id INTEGER NOT NULL,
    amount_czk INTEGER NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    calculation_type VARCHAR(50),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(grade_id) REFERENCES grades(id) ON DELETE CASCADE
);

-- payouts
CREATE TABLE IF NOT EXISTS payouts (
    id INTEGER PRIMARY KEY,
    ln_address VARCHAR(255) NOT NULL,
    amount_czk INTEGER NOT NULL,
    amount_sats INTEGER NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    invoice TEXT,
    payment_hash VARCHAR(255),
    error_message TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME
);

-- payout_audits
CREATE TABLE IF NOT EXISTS payout_audits (
    id INTEGER PRIMARY KEY,
    payout_id INTEGER NOT NULL,
    event VARCHAR(50) NOT NULL,
    details TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(payout_id) REFERENCES payouts(id) ON DELETE CASCADE
);

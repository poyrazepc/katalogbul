-- Keşfedilen PDF'ler tablosu
-- Kaynak tarama sonuçları burada saklanır

CREATE TABLE IF NOT EXISTS discovered_pdfs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_hash TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    domain TEXT NOT NULL,
    source_path TEXT,
    size_bytes INTEGER,
    size_mb REAL,
    brand TEXT,
    model TEXT,
    category TEXT,
    is_valid BOOLEAN DEFAULT 1,
    discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_checked DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Taranan domain'ler tablosu
CREATE TABLE IF NOT EXISTS scanned_domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT UNIQUE NOT NULL,
    total_pdfs INTEGER DEFAULT 0,
    last_scanned DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'completed'
);

-- Index'ler
CREATE INDEX IF NOT EXISTS idx_discovered_pdfs_domain ON discovered_pdfs(domain);
CREATE INDEX IF NOT EXISTS idx_discovered_pdfs_brand ON discovered_pdfs(brand);
CREATE INDEX IF NOT EXISTS idx_discovered_pdfs_category ON discovered_pdfs(category);
CREATE INDEX IF NOT EXISTS idx_discovered_pdfs_size ON discovered_pdfs(size_bytes);
CREATE INDEX IF NOT EXISTS idx_scanned_domains_domain ON scanned_domains(domain);


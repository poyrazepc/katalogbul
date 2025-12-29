-- Migration: Kaynak Tarama Sistemi
-- Tarih: 2024-12-28
-- Açıklama: Yeni tablolar - discovered_sources, scanned_pdfs, scan_history, premium_results

-- Keşfedilen Kaynaklar (Path'ler)
CREATE TABLE IF NOT EXISTS discovered_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    base_domain TEXT NOT NULL,
    discovered_path TEXT NOT NULL,
    full_url TEXT NOT NULL,
    origin_url TEXT,
    origin_query TEXT,
    pdf_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'scanning', 'completed', 'failed')),
    error_message TEXT,
    last_scanned DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(base_domain, discovered_path)
);

-- Tarama ile Bulunan PDF'ler
CREATE TABLE IF NOT EXISTS scanned_pdfs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES discovered_sources(id) ON DELETE CASCADE,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    snippet TEXT,
    detected_brand TEXT,
    detected_model TEXT,
    file_size INTEGER,
    is_verified BOOLEAN DEFAULT 0,
    discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Tarama Geçmişi (Yapıldı bölümü için)
CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES discovered_sources(id),
    scan_type TEXT DEFAULT 'manual',
    pdfs_found INTEGER DEFAULT 0,
    new_pdfs INTEGER DEFAULT 0,
    duration_seconds INTEGER,
    started_at DATETIME,
    completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_by INTEGER REFERENCES users(id)
);

-- Premium Sonuçlar Cache
CREATE TABLE IF NOT EXISTS premium_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_hash TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    snippet TEXT,
    platform TEXT,
    domain TEXT,
    query TEXT,
    view_count INTEGER DEFAULT 1,
    discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Index'ler
CREATE INDEX IF NOT EXISTS idx_discovered_sources_domain ON discovered_sources(base_domain);
CREATE INDEX IF NOT EXISTS idx_discovered_sources_status ON discovered_sources(status);
CREATE INDEX IF NOT EXISTS idx_scanned_pdfs_source ON scanned_pdfs(source_id);
CREATE INDEX IF NOT EXISTS idx_scanned_pdfs_brand ON scanned_pdfs(detected_brand);
CREATE INDEX IF NOT EXISTS idx_scan_history_source ON scan_history(source_id);
CREATE INDEX IF NOT EXISTS idx_premium_results_platform ON premium_results(platform);

-- Migration tamamlandı
SELECT 'Migration completed: source_scanner_tables' as status;

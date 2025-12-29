import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Optional, Any

from src.config import DATABASE_PATH

class PEPCDatabase:
    """SQLite veritabanı yönetimi - Gelişmiş Sürüm"""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv('DATABASE_PATH') or DATABASE_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_database()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_database(self):
        """Tabloları oluştur"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.executescript('''
            -- PDF Kaynakları (Siteler)
            CREATE TABLE IF NOT EXISTS pdf_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT UNIQUE NOT NULL,
                base_url TEXT,
                url_pattern TEXT,
                discovery_method TEXT,
                status TEXT DEFAULT 'active',
                pdf_count INTEGER DEFAULT 0,
                brands TEXT,  -- JSON array
                last_checked DATETIME,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            -- PDF Katalogları
            CREATE TABLE IF NOT EXISTS pdf_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER REFERENCES pdf_sources(id),
                url TEXT UNIQUE NOT NULL,
                filename TEXT,
                title TEXT,
                brand TEXT,
                model TEXT,
                equipment_type TEXT,
                doc_type TEXT,
                language TEXT,
                file_size INTEGER,
                page_count INTEGER,
                thumbnail_path TEXT,
                status TEXT DEFAULT 'active', -- active, broken, pending
                discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                verified BOOLEAN DEFAULT FALSE,
                download_count INTEGER DEFAULT 0
            );
            
            -- Görev Kuyruğu
            CREATE TABLE IF NOT EXISTS task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL, -- discovery, processing, validation
                payload TEXT, -- JSON payload
                status TEXT DEFAULT 'pending', -- pending, processing, completed, failed
                error_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Arama Sorguları Log
            CREATE TABLE IF NOT EXISTS search_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                language TEXT,
                results_count INTEGER,
                pdf_count INTEGER,
                executed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Search Cache (sonsuza kadar saklama, yeni sonuçlar merge edilir)
            CREATE TABLE IF NOT EXISTS search_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT UNIQUE NOT NULL,
                engine TEXT NOT NULL,
                query TEXT NOT NULL,
                language TEXT,
                doc_type TEXT,
                results TEXT,  -- JSON array of results
                result_count INTEGER DEFAULT 0,
                page_count INTEGER,
                file_size_bytes INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL
            );
            
            -- ================================================================
            -- KULLANICI VE KREDİ SİSTEMİ TABLOLARI
            -- ================================================================
            
            -- Kullanıcılar
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                phone TEXT,
                hashed_password TEXT NOT NULL,
                role TEXT DEFAULT 'user' CHECK(role IN ('user', 'admin', 'superadmin')),
                credit_balance INTEGER DEFAULT 50,
                subscription_tier TEXT DEFAULT 'free' CHECK(subscription_tier IN ('free', 'pro', 'enterprise')),
                subscription_expires_at DATETIME,
                daily_search_count INTEGER DEFAULT 0,
                last_search_date DATE,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_login DATETIME
            );
            
            -- Ayarlar (Şifreli API key'ler ve sistem ayarları)
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,  -- api_keys, payment, pricing, general
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                is_encrypted BOOLEAN DEFAULT 0,
                description TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_by INTEGER REFERENCES users(id)
            );
            
            -- Ödemeler
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                merchant_oid TEXT UNIQUE NOT NULL,
                package_type TEXT NOT NULL,
                amount INTEGER NOT NULL,  -- Kuruş cinsinden
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'success', 'failed')),
                paytr_response TEXT,  -- JSON
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            );
            
            -- Kredi Talepleri
            CREATE TABLE IF NOT EXISTS credit_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                package_type TEXT NOT NULL,  -- credits_100, credits_500, credits_1000
                credit_amount INTEGER NOT NULL,  -- 100, 500, 1000
                price_amount INTEGER NOT NULL,  -- Kuruş cinsinden (4900, 19900, 34900)
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
                admin_note TEXT,
                processed_by INTEGER REFERENCES users(id),
                processed_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Arama Logları (Detaylı)
            CREATE TABLE IF NOT EXISTS search_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),  -- NULL = guest
                query TEXT NOT NULL,
                doc_type TEXT,
                engines_used TEXT,  -- JSON array
                result_count INTEGER DEFAULT 0,
                credits_used INTEGER DEFAULT 0,
                is_cached BOOLEAN DEFAULT 0,
                ip_address TEXT,
                user_agent TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Admin Aktivite Logları
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL REFERENCES users(id),
                action TEXT NOT NULL,
                target_table TEXT,
                target_id INTEGER,
                old_value TEXT,
                new_value TEXT,
                ip_address TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Şifre Sıfırlama Tokenleri
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                token TEXT UNIQUE NOT NULL,
                expires_at DATETIME NOT NULL,
                used BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Favoriler
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                pdf_url TEXT NOT NULL,
                title TEXT,
                snippet TEXT,
                file_size TEXT,
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, pdf_url)
            );
            
            -- ================================================================
            -- KATALOG ÖĞRENME SİSTEMİ TABLOLARI
            -- ================================================================
            
            -- Kullanıcının Yüklediği Kataloglar
            CREATE TABLE IF NOT EXISTS user_catalogs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                filename TEXT NOT NULL,
                original_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER,
                total_pages INTEGER,
                brand TEXT,
                model TEXT,
                catalog_type TEXT,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'uploading', 'analyzing', 'completed', 'failed')),
                progress INTEGER DEFAULT 0,
                progress_message TEXT,
                error_message TEXT,
                fingerprint_hash TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                analyzed_at DATETIME,
                last_viewed DATETIME
            );
            
            -- Öğrenilen Katalog Kuralları
            CREATE TABLE IF NOT EXISTS catalog_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalog_id INTEGER NOT NULL REFERENCES user_catalogs(id) ON DELETE CASCADE,
                rule_type TEXT NOT NULL CHECK(rule_type IN ('toc', 'table', 'layout', 'structure')),
                rules_json TEXT NOT NULL,
                copied_from INTEGER REFERENCES user_catalogs(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(catalog_id, rule_type)
            );
            
            -- Çıkarılan Kategoriler
            CREATE TABLE IF NOT EXISTS catalog_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalog_id INTEGER NOT NULL REFERENCES user_catalogs(id) ON DELETE CASCADE,
                parent_id INTEGER REFERENCES catalog_categories(id),
                title TEXT NOT NULL,
                page_start INTEGER,
                page_end INTEGER,
                level INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Çıkarılan Parçalar
            CREATE TABLE IF NOT EXISTS catalog_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalog_id INTEGER NOT NULL REFERENCES user_catalogs(id) ON DELETE CASCADE,
                category_id INTEGER REFERENCES catalog_categories(id),
                page_number INTEGER NOT NULL,
                item_number INTEGER,
                part_no TEXT,
                description TEXT,
                qty INTEGER DEFAULT 1,
                remarks TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Katalog Parmak İzleri (Benzer katalog tespiti için)
            CREATE TABLE IF NOT EXISTS catalog_fingerprints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalog_id INTEGER NOT NULL REFERENCES user_catalogs(id) ON DELETE CASCADE,
                fingerprint_type TEXT NOT NULL,
                fingerprint_value TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(catalog_id, fingerprint_type)
            );
            
            -- Analiz İlerleme Logları (SSE için)
            CREATE TABLE IF NOT EXISTS catalog_analysis_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalog_id INTEGER NOT NULL REFERENCES user_catalogs(id) ON DELETE CASCADE,
                step TEXT NOT NULL,
                progress INTEGER DEFAULT 0,
                message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            -- ================================================================
            -- KAYNAK TARAMA SİSTEMİ (Admin için)
            -- ================================================================
            
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
            
            -- Keşfedilen PDF'ler (kaynak tarama sonuçları)
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
            
            -- Taranan domain'ler
            CREATE TABLE IF NOT EXISTS scanned_domains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT UNIQUE NOT NULL,
                total_pdfs INTEGER DEFAULT 0,
                last_scanned DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'completed'
            );
            
            -- Index'ler
            CREATE INDEX IF NOT EXISTS idx_catalog_brand ON pdf_catalog(brand);
            CREATE INDEX IF NOT EXISTS idx_catalog_model ON pdf_catalog(model);
            CREATE INDEX IF NOT EXISTS idx_catalog_status ON pdf_catalog(status);
            CREATE INDEX IF NOT EXISTS idx_queue_status ON task_queue(status);
            CREATE INDEX IF NOT EXISTS idx_cache_key ON search_cache(cache_key);
            CREATE INDEX IF NOT EXISTS idx_cache_expires ON search_cache(expires_at);
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            CREATE INDEX IF NOT EXISTS idx_users_tier ON users(subscription_tier);
            CREATE INDEX IF NOT EXISTS idx_settings_category ON settings(category);
            CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
            CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
            CREATE INDEX IF NOT EXISTS idx_search_logs_user ON search_logs(user_id);
            CREATE INDEX IF NOT EXISTS idx_search_logs_date ON search_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_password_tokens_user ON password_reset_tokens(user_id);
            CREATE INDEX IF NOT EXISTS idx_password_tokens_token ON password_reset_tokens(token);
            CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);
            
            -- Katalog tabloları index'leri
            CREATE INDEX IF NOT EXISTS idx_user_catalogs_user ON user_catalogs(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_catalogs_status ON user_catalogs(status);
            CREATE INDEX IF NOT EXISTS idx_catalog_rules_catalog ON catalog_rules(catalog_id);
            CREATE INDEX IF NOT EXISTS idx_catalog_categories_catalog ON catalog_categories(catalog_id);
            CREATE INDEX IF NOT EXISTS idx_catalog_parts_catalog ON catalog_parts(catalog_id);
            CREATE INDEX IF NOT EXISTS idx_catalog_parts_page ON catalog_parts(page_number);
            CREATE INDEX IF NOT EXISTS idx_catalog_fingerprints_catalog ON catalog_fingerprints(catalog_id);
        ''')
        
        conn.commit()
        conn.close()

    def add_pdf(self, data: Dict[str, Any]) -> int:
        """PDF'i veritabanına ekle veya güncelle"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Önce domain'i bul veya ekle
            domain = data.get('domain')
            cursor.execute("INSERT OR IGNORE INTO pdf_sources (domain) VALUES (?)", (domain,))
            cursor.execute("SELECT id FROM pdf_sources WHERE domain = ?", (domain,))
            source_id = cursor.fetchone()[0]

            cursor.execute('''
                INSERT INTO pdf_catalog 
                (source_id, url, filename, title, brand, equipment_type, doc_type, language, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title = excluded.title,
                    brand = COALESCE(excluded.brand, brand),
                    equipment_type = COALESCE(excluded.equipment_type, equipment_type),
                    doc_type = COALESCE(excluded.doc_type, doc_type),
                    language = COALESCE(excluded.language, language)
                RETURNING id
            ''', (
                source_id,
                data['url'],
                data.get('filename', data['url'].split('/')[-1]),
                data.get('title'),
                data.get('brand'),
                data.get('equipment_type'),
                data.get('doc_type'),
                data.get('language'),
                data.get('status', 'active')
            ))
            pdf_id = cursor.fetchone()[0]
            conn.commit()
            return pdf_id
        except Exception as e:
            print(f"Database error in add_pdf: {e}")
            return -1
        finally:
            conn.close()

    def update_pdf_metadata(self, pdf_id: int, page_count: int, thumbnail_path: str, file_size: int = None):
        """PDF meta verilerini güncelle"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            query = "UPDATE pdf_catalog SET page_count = ?, thumbnail_path = ?, verified = 1"
            params = [page_count, thumbnail_path]
            if file_size:
                query += ", file_size = ?"
                params.append(file_size)
            query += " WHERE id = ?"
            params.append(pdf_id)
            
            cursor.execute(query, params)
            conn.commit()
        finally:
            conn.close()

    def add_task(self, task_type: str, payload: Dict) -> int:
        """Kuyruğa yeni görev ekle"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO task_queue (task_type, payload) VALUES (?, ?)",
                (task_type, json.dumps(payload))
            )
            task_id = cursor.lastrowid
            conn.commit()
            return task_id
        finally:
            conn.close()

    def get_pending_tasks(self, limit: int = 10) -> List[Dict]:
        """Bekleyen görevleri al"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM task_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
            (limit,)
        )
        tasks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return tasks

    def update_task_status(self, task_id: int, status: str, error_message: str = None):
        """Görev durumunu güncelle"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE task_queue SET status = ?, error_message = ?, updated_at = ? WHERE id = ?",
            (status, error_message, datetime.now().isoformat(), task_id)
        )
        conn.commit()
        conn.close()

    def search_catalog(self, filters: Dict, limit: int = 20, offset: int = 0) -> List[Dict]:
        """Katalogda filtreli arama yap"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # active ve pending durumundaki PDF'leri getir (broken hariç)
        query = "SELECT * FROM pdf_catalog WHERE status IN ('active', 'pending')"
        params = []
        
        for key, value in filters.items():
            if value:
                if key in ['brand', 'model', 'title']:
                    query += f" AND {key} LIKE ?"
                    params.append(f"%{value}%")
                else:
                    query += f" AND {key} = ?"
                    params.append(value)
        
        query += " ORDER BY status ASC, discovered_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results


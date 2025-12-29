"""
Search Cache Manager - 30 günlük önbellek yönetimi
"""
import sqlite3
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from src.config import DATABASE_PATH, CACHE_EXPIRY_DAYS


class CacheManager:
    """Arama sonuçları için önbellek yönetimi"""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DATABASE_PATH
        self.expiry_days = CACHE_EXPIRY_DAYS
    
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _generate_cache_key(self, engine: str, query: str, language: str = None, doc_type: str = None, page: int = None) -> str:
        """Benzersiz cache key oluştur - sayfa bazlı"""
        key_parts = [engine, query.lower().strip()]
        if language:
            key_parts.append(language)
        if doc_type:
            key_parts.append(doc_type)
        if page is not None:
            key_parts.append(f"p{page}")
        
        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def get_cached_results(
        self, 
        engine: str, 
        query: str, 
        language: str = None, 
        doc_type: str = None,
        page: int = None
    ) -> Optional[List[Dict]]:
        """Cache'den sonuçları getir (varsa ve süresi dolmamışsa) - sayfa bazlı"""
        cache_key = self._generate_cache_key(engine, query, language, doc_type, page)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT results FROM search_cache 
                WHERE cache_key = ? AND expires_at > datetime('now')
            ''', (cache_key,))
            
            row = cursor.fetchone()
            if row:
                return json.loads(row['results'])
            return None
        finally:
            conn.close()
    
    def save_to_cache(
        self,
        engine: str,
        query: str,
        results: List[Dict],
        language: str = None,
        doc_type: str = None,
        page: int = None
    ) -> bool:
        """Sonuçları cache'e kaydet - sayfa bazlı, yeni sonuçlar eskilerle birleştirilir (merge)"""
        cache_key = self._generate_cache_key(engine, query, language, doc_type, page)
        expires_at = datetime.now() + timedelta(days=self.expiry_days)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Önce mevcut sonuçları al
            cursor.execute('''
                SELECT results FROM search_cache WHERE cache_key = ?
            ''', (cache_key,))
            
            row = cursor.fetchone()
            
            if row:
                # Mevcut sonuçlar var - birleştir (merge)
                existing_results = json.loads(row['results'])
                existing_urls = {r.get('url', '').lower() for r in existing_results}
                
                # Yeni sonuçlardan sadece yeni URL'leri ekle
                new_unique_results = []
                for r in results:
                    url = r.get('url', '').lower()
                    if url and url not in existing_urls:
                        new_unique_results.append(r)
                        existing_urls.add(url)
                
                # Birleştirilmiş sonuçlar
                merged_results = existing_results + new_unique_results
                
                cursor.execute('''
                    UPDATE search_cache SET
                        results = ?,
                        result_count = ?,
                        updated_at = datetime('now'),
                        expires_at = ?
                    WHERE cache_key = ?
                ''', (
                    json.dumps(merged_results, ensure_ascii=False),
                    len(merged_results),
                    expires_at.isoformat(),
                    cache_key
                ))
                
                if new_unique_results:
                    print(f"Cache merge: +{len(new_unique_results)} yeni sonuç eklendi (toplam: {len(merged_results)})")
            else:
                # Yeni kayıt
                cursor.execute('''
                    INSERT INTO search_cache 
                    (cache_key, engine, query, language, doc_type, results, result_count, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    cache_key,
                    engine,
                    query,
                    language,
                    doc_type,
                    json.dumps(results, ensure_ascii=False),
                    len(results),
                    expires_at.isoformat()
                ))
                print(f"Cache new: {len(results)} sonuç kaydedildi")
            
            conn.commit()
            return True
        except Exception as e:
            print(f"Cache save error: {e}")
            return False
        finally:
            conn.close()
    
    def clear_expired_cache(self) -> int:
        """Süresi dolmuş cache kayıtlarını temizle"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM search_cache WHERE expires_at < datetime('now')")
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count
        finally:
            conn.close()
    
    def clear_engine_cache(self, engine: str) -> int:
        """Belirli bir motorun cache'ini temizle"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM search_cache WHERE engine = ?", (engine,))
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count
        finally:
            conn.close()
    
    def clear_all_cache(self) -> int:
        """Tüm cache'i temizle"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM search_cache")
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count
        finally:
            conn.close()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Cache istatistiklerini getir"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Toplam kayıt
            cursor.execute("SELECT COUNT(*) as total FROM search_cache")
            total = cursor.fetchone()['total']
            
            # Motor bazında
            cursor.execute('''
                SELECT engine, COUNT(*) as count, SUM(result_count) as total_results
                FROM search_cache 
                WHERE expires_at > datetime('now')
                GROUP BY engine
            ''')
            by_engine = {row['engine']: {
                'count': row['count'],
                'total_results': row['total_results']
            } for row in cursor.fetchall()}
            
            # Süresi dolmuş
            cursor.execute("SELECT COUNT(*) as expired FROM search_cache WHERE expires_at < datetime('now')")
            expired = cursor.fetchone()['expired']
            
            return {
                'total_cached': total,
                'expired': expired,
                'active': total - expired,
                'by_engine': by_engine
            }
        finally:
            conn.close()


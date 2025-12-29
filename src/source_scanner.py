"""
Kaynak Tarama Modülü
Admin panelden manuel çalıştırılır

Akış:
1. Kullanıcı aramasından PDF URL bulunur
2. URL'den path'ler çıkarılır (örn: /upload/user55/)
3. Admin taramayı başlatır
4. Serper ile site:xxx.com/path/ filetype:pdf aranır
5. Sonuçlar DB'ye kaydedilir
"""
import asyncio
import aiohttp
import hashlib
import re
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# Bilinen marka listesi (brand detection için)
KNOWN_BRANDS = [
    "volvo", "caterpillar", "cat", "komatsu", "hitachi", "liebherr",
    "jcb", "case", "john deere", "bobcat", "kubota", "doosan", "hyundai",
    "kobelco", "sumitomo", "takeuchi", "yanmar", "ihi", "tadano", "grove",
    "terex", "manitou", "merlo", "haulotte", "genie", "skyjack", "snorkel",
    "atlas copco", "ingersoll rand", "sullair", "chicago pneumatic",
    "cummins", "perkins", "deutz", "isuzu", "mitsubishi", "hino",
    "scania", "man", "daf", "iveco", "mercedes", "renault trucks"
]


@dataclass
class DiscoveredSource:
    base_domain: str
    discovered_path: str
    full_url: str
    origin_url: str
    origin_query: str


@dataclass
class ScannedPdf:
    url: str
    title: str
    snippet: str
    detected_brand: Optional[str]
    detected_model: Optional[str]


class SourceScanner:
    """
    Kaynak tarama sistemi
    - Path extraction
    - Serper ile tarama
    - DB kayıt
    """
    
    def __init__(self, db, serper_api_key: str = None):
        self.db = db
        self.serper_api_key = serper_api_key or os.getenv("SERPER_API_KEY")
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _ensure_session(self):
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    # =========================================
    # PATH EXTRACTION
    # =========================================
    
    def extract_paths_from_url(self, url: str) -> List[str]:
        """
        URL'den taranabilir path'leri çıkar
        
        Örnek:
        Input: https://example.com/upload/user55/volvo-ec210.pdf
        Output: [
            "site:example.com/upload/user55/",
            "site:example.com/upload/",
            "site:example.com"
        ]
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")
            path = parsed.path
            
            # .pdf kısmını çıkar
            if path.endswith(".pdf"):
                path = "/".join(path.split("/")[:-1]) + "/"
            
            paths = []
            path_parts = [p for p in path.split("/") if p]
            
            # Her seviye için path oluştur
            for i in range(len(path_parts), 0, -1):
                sub_path = "/" + "/".join(path_parts[:i]) + "/"
                paths.append(f"site:{domain}{sub_path}")
            
            # Domain seviyesi
            paths.append(f"site:{domain}")
            
            return paths
            
        except Exception as e:
            logger.error(f"Path extraction error: {e}")
            return []
    
    def extract_source_info(self, url: str, query: str) -> List[DiscoveredSource]:
        """URL'den kaynak bilgilerini çıkar"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")
            path = parsed.path
            
            # .pdf kısmını çıkar
            if path.endswith(".pdf"):
                path = "/".join(path.split("/")[:-1]) + "/"
            
            sources = []
            path_parts = [p for p in path.split("/") if p]
            
            # Her seviye için kaynak oluştur
            for i in range(len(path_parts), 0, -1):
                sub_path = "/" + "/".join(path_parts[:i]) + "/"
                full_url = f"https://{domain}{sub_path}"
                
                sources.append(DiscoveredSource(
                    base_domain=domain,
                    discovered_path=sub_path,
                    full_url=full_url,
                    origin_url=url,
                    origin_query=query
                ))
            
            # Domain seviyesi
            sources.append(DiscoveredSource(
                base_domain=domain,
                discovered_path="/",
                full_url=f"https://{domain}/",
                origin_url=url,
                origin_query=query
            ))
            
            return sources
            
        except Exception as e:
            logger.error(f"Source extraction error: {e}")
            return []
    
    # =========================================
    # DATABASE OPERATIONS
    # =========================================
    
    def save_discovered_source(self, source: DiscoveredSource) -> int:
        """Keşfedilen kaynağı DB'ye kaydet"""
        conn = self.db.get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO discovered_sources 
                (base_domain, discovered_path, full_url, origin_url, origin_query)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(base_domain, discovered_path) DO UPDATE SET
                    origin_url = COALESCE(excluded.origin_url, origin_url),
                    origin_query = COALESCE(excluded.origin_query, origin_query)
                RETURNING id
            """, (
                source.base_domain,
                source.discovered_path,
                source.full_url,
                source.origin_url,
                source.origin_query
            ))
            result = cursor.fetchone()
            conn.commit()
            return result[0] if result else -1
        except Exception as e:
            logger.error(f"Save source error: {e}")
            return -1
        finally:
            conn.close()
    
    def get_pending_sources(self, limit: int = 50) -> List[Dict]:
        """Bekleyen kaynakları getir"""
        conn = self.db.get_connection()
        try:
            cursor = conn.execute("""
                SELECT * FROM discovered_sources 
                WHERE status = 'pending'
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_completed_sources(self, limit: int = 50) -> List[Dict]:
        """Tamamlanan kaynakları getir (Yapıldı bölümü)"""
        conn = self.db.get_connection()
        try:
            cursor = conn.execute("""
                SELECT ds.*, 
                       COUNT(sp.id) as total_pdfs,
                       sh.completed_at as last_scan_date,
                       sh.new_pdfs as last_new_pdfs
                FROM discovered_sources ds
                LEFT JOIN scanned_pdfs sp ON sp.source_id = ds.id
                LEFT JOIN scan_history sh ON sh.source_id = ds.id
                WHERE ds.status = 'completed'
                GROUP BY ds.id
                ORDER BY sh.completed_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_all_sources(self) -> Dict[str, List[Dict]]:
        """Tüm kaynakları duruma göre grupla"""
        conn = self.db.get_connection()
        try:
            # Bekleyenler
            cursor = conn.execute("""
                SELECT * FROM discovered_sources 
                WHERE status = 'pending'
                ORDER BY created_at DESC
            """)
            pending = [dict(row) for row in cursor.fetchall()]
            
            # Tamamlananlar
            cursor = conn.execute("""
                SELECT ds.*, 
                       COUNT(sp.id) as total_pdfs
                FROM discovered_sources ds
                LEFT JOIN scanned_pdfs sp ON sp.source_id = ds.id
                WHERE ds.status = 'completed'
                GROUP BY ds.id
                ORDER BY ds.last_scanned DESC
            """)
            completed = [dict(row) for row in cursor.fetchall()]
            
            # Taranıyor
            cursor = conn.execute("""
                SELECT * FROM discovered_sources 
                WHERE status = 'scanning'
            """)
            scanning = [dict(row) for row in cursor.fetchall()]
            
            # Hatalılar
            cursor = conn.execute("""
                SELECT * FROM discovered_sources 
                WHERE status = 'failed'
                ORDER BY last_scanned DESC
            """)
            failed = [dict(row) for row in cursor.fetchall()]
            
            return {
                "pending": pending,
                "completed": completed,
                "scanning": scanning,
                "failed": failed
            }
        finally:
            conn.close()
    
    def get_scanned_pdfs(self, source_id: int) -> List[Dict]:
        """Bir kaynaktan bulunan PDF'leri getir"""
        conn = self.db.get_connection()
        try:
            cursor = conn.execute("""
                SELECT * FROM scanned_pdfs 
                WHERE source_id = ?
                ORDER BY discovered_at DESC
            """, (source_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    # =========================================
    # BRAND DETECTION
    # =========================================
    
    def detect_brand(self, text: str) -> Optional[str]:
        """Metinden marka tespit et"""
        text_lower = text.lower()
        for brand in KNOWN_BRANDS:
            if brand in text_lower:
                return brand.title()
        return None
    
    def detect_model(self, text: str) -> Optional[str]:
        """Metinden model tespit et (basit pattern)"""
        # Yaygın model pattern'leri
        patterns = [
            r'\b([A-Z]{1,3}[-\s]?\d{2,4}[A-Z]?)\b',  # EC210, PC200-8, D6R
            r'\b(\d{3,4}[A-Z]{1,2})\b',  # 320D, 980H
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text.upper())
            if match:
                return match.group(1)
        return None
    
    # =========================================
    # SCANNING
    # =========================================
    
    async def scan_source(self, source_id: int) -> Dict:
        """
        Tek bir kaynağı tara
        
        Returns:
            {"success": bool, "pdfs_found": int, "new_pdfs": int}
        """
        conn = self.db.get_connection()
        start_time = datetime.now()
        
        try:
            # Kaynağı al
            cursor = conn.execute(
                "SELECT * FROM discovered_sources WHERE id = ?", 
                (source_id,)
            )
            source = cursor.fetchone()
            if not source:
                return {"success": False, "error": "Source not found"}
            
            source = dict(source)
            
            # Durumu güncelle
            conn.execute(
                "UPDATE discovered_sources SET status = 'scanning' WHERE id = ?",
                (source_id,)
            )
            conn.commit()
            
            # Serper ile ara
            query = f"site:{source['base_domain']}{source['discovered_path']} filetype:pdf"
            
            await self._ensure_session()
            
            results = await self._serper_search(query)
            
            if results is None:
                conn.execute("""
                    UPDATE discovered_sources 
                    SET status = 'failed', error_message = 'Serper API error'
                    WHERE id = ?
                """, (source_id,))
                conn.commit()
                return {"success": False, "error": "Serper API error"}
            
            # PDF'leri kaydet
            pdfs_found = 0
            new_pdfs = 0
            
            for r in results:
                url = r.get("link", "")
                if not url.lower().endswith(".pdf"):
                    continue
                
                pdfs_found += 1
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                
                # Brand/model tespit
                full_text = f"{title} {snippet} {url}"
                detected_brand = self.detect_brand(full_text)
                detected_model = self.detect_model(full_text)
                
                # Kaydet
                try:
                    conn.execute("""
                        INSERT INTO scanned_pdfs 
                        (source_id, url, title, snippet, detected_brand, detected_model)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(url) DO NOTHING
                    """, (
                        source_id, url, title[:500], snippet[:1000],
                        detected_brand, detected_model
                    ))
                    if conn.total_changes > 0:
                        new_pdfs += 1
                except:
                    pass
            
            # Kaynağı güncelle
            conn.execute("""
                UPDATE discovered_sources 
                SET status = 'completed', 
                    pdf_count = ?,
                    last_scanned = datetime('now'),
                    error_message = NULL
                WHERE id = ?
            """, (pdfs_found, source_id))
            
            # Geçmişe kaydet
            duration = (datetime.now() - start_time).seconds
            conn.execute("""
                INSERT INTO scan_history 
                (source_id, scan_type, pdfs_found, new_pdfs, duration_seconds, started_at)
                VALUES (?, 'manual', ?, ?, ?, ?)
            """, (source_id, pdfs_found, new_pdfs, duration, start_time.isoformat()))
            
            conn.commit()
            
            logger.info(f"Source {source_id} scanned: {pdfs_found} PDFs, {new_pdfs} new")
            
            return {
                "success": True,
                "pdfs_found": pdfs_found,
                "new_pdfs": new_pdfs,
                "duration_seconds": duration
            }
            
        except Exception as e:
            logger.error(f"Scan error: {e}")
            conn.execute("""
                UPDATE discovered_sources 
                SET status = 'failed', error_message = ?
                WHERE id = ?
            """, (str(e)[:500], source_id))
            conn.commit()
            return {"success": False, "error": str(e)}
        finally:
            conn.close()
    
    async def _serper_search(self, query: str, num: int = 100) -> Optional[List[Dict]]:
        """Serper API ile arama yap"""
        if not self.serper_api_key:
            logger.error("Serper API key not configured")
            return None
        
        try:
            url = "https://google.serper.dev/search"
            headers = {
                "X-API-KEY": self.serper_api_key,
                "Content-Type": "application/json"
            }
            payload = {
                "q": query,
                "num": num
            }
            
            async with self.session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("organic", [])
                else:
                    logger.error(f"Serper error: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"Serper request error: {e}")
            return None
    
    async def scan_multiple_sources(self, source_ids: List[int]) -> Dict:
        """Birden fazla kaynağı tara"""
        results = {
            "total": len(source_ids),
            "success": 0,
            "failed": 0,
            "total_pdfs": 0,
            "new_pdfs": 0
        }
        
        for source_id in source_ids:
            result = await self.scan_source(source_id)
            if result.get("success"):
                results["success"] += 1
                results["total_pdfs"] += result.get("pdfs_found", 0)
                results["new_pdfs"] += result.get("new_pdfs", 0)
            else:
                results["failed"] += 1
        
        await self.close()
        return results
    
    # =========================================
    # AUTO DISCOVERY (Arama sonuçlarından)
    # =========================================
    
    def process_search_results(self, results: List[Dict], query: str):
        """
        Arama sonuçlarından kaynak keşfet
        (Her aramadan sonra otomatik çağrılır)
        """
        for r in results:
            url = r.get("url", "")
            if not url:
                continue
            
            # Premium siteler hariç (scribd, issuu vb.)
            premium_domains = [
                "scribd.com", "issuu.com", "slideshare.net", 
                "academia.edu", "calameo.com", "yumpu.com"
            ]
            
            is_premium = any(d in url.lower() for d in premium_domains)
            if is_premium:
                continue
            
            # PDF URL'lerinden kaynak çıkar
            if ".pdf" in url.lower():
                sources = self.extract_source_info(url, query)
                for source in sources:
                    self.save_discovered_source(source)
    
    # =========================================
    # STATISTICS
    # =========================================
    
    def get_statistics(self) -> Dict:
        """İstatistikleri getir"""
        conn = self.db.get_connection()
        try:
            stats = {}
            
            # Kaynak sayıları
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count 
                FROM discovered_sources 
                GROUP BY status
            """)
            stats["sources_by_status"] = {
                row["status"]: row["count"] 
                for row in cursor.fetchall()
            }
            
            # Toplam PDF
            cursor = conn.execute("SELECT COUNT(*) FROM scanned_pdfs")
            stats["total_pdfs"] = cursor.fetchone()[0]
            
            # Marka dağılımı
            cursor = conn.execute("""
                SELECT detected_brand, COUNT(*) as count 
                FROM scanned_pdfs 
                WHERE detected_brand IS NOT NULL
                GROUP BY detected_brand
                ORDER BY count DESC
                LIMIT 20
            """)
            stats["brand_distribution"] = {
                row["detected_brand"]: row["count"]
                for row in cursor.fetchall()
            }
            
            # Son taramalar
            cursor = conn.execute("""
                SELECT sh.*, ds.base_domain, ds.discovered_path
                FROM scan_history sh
                JOIN discovered_sources ds ON ds.id = sh.source_id
                ORDER BY sh.completed_at DESC
                LIMIT 10
            """)
            stats["recent_scans"] = [dict(row) for row in cursor.fetchall()]
            
            return stats
        finally:
            conn.close()
    
    def delete_source(self, source_id: int) -> bool:
        """Kaynağı sil"""
        conn = self.db.get_connection()
        try:
            conn.execute("DELETE FROM discovered_sources WHERE id = ?", (source_id,))
            conn.commit()
            return True
        except:
            return False
        finally:
            conn.close()
    
    def reset_source(self, source_id: int) -> bool:
        """Kaynağı pending'e döndür"""
        conn = self.db.get_connection()
        try:
            conn.execute("""
                UPDATE discovered_sources 
                SET status = 'pending', error_message = NULL 
                WHERE id = ?
            """, (source_id,))
            conn.commit()
            return True
        except:
            return False
        finally:
            conn.close()

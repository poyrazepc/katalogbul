"""
Kaynak Keşif Modülü - Firecrawl /map Entegrasyonu

Arama sonuçlarındaki PDF URL'lerinden:
1. Benzersiz domain'leri çıkar
2. Firecrawl /map ile site haritasını al
3. PDF'leri filtrele
4. HTTP HEAD ile boyut bilgisi al

Maliyet: 1 kredi / map çağrısı
"""
import asyncio
import aiohttp
import os
import hashlib
from typing import List, Dict, Optional, Set, Tuple, AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin
import logging

logger = logging.getLogger(__name__)


@dataclass
class SourceDomain:
    """Benzersiz kaynak domain bilgisi"""
    domain: str
    paths: List[str] = field(default_factory=list)  # Bulunan path'ler
    pdf_count: int = 0  # Aramada bulunan PDF sayısı
    status: str = "pending"  # pending, scanning, completed, error
    progress: int = 0  # 0-100
    scanned_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "domain": self.domain,
            "paths": self.paths,
            "pdf_count": self.pdf_count,
            "status": self.status,
            "progress": self.progress,
            "scanned_at": self.scanned_at.isoformat() if self.scanned_at else None,
            "error_message": self.error_message
        }


@dataclass
class DiscoveredPDF:
    """Keşfedilen PDF bilgisi"""
    url: str
    title: str = ""
    source_domain: str = ""
    source_path: str = ""
    size_bytes: Optional[int] = None
    size_mb: Optional[float] = None
    is_valid: bool = True
    discovered_at: datetime = field(default_factory=datetime.now)
    
    @property
    def size_formatted(self) -> str:
        if self.size_bytes is None:
            return "?"
        elif self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        elif self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        else:
            return f"{self.size_bytes / (1024 * 1024):.1f} MB"
    
    def to_dict(self) -> Dict:
        return {
            "url": self.url,
            "title": self.title,
            "source_domain": self.source_domain,
            "source_path": self.source_path,
            "size_bytes": self.size_bytes,
            "size_mb": self.size_mb,
            "size_formatted": self.size_formatted,
            "is_valid": self.is_valid,
            "discovered_at": self.discovered_at.isoformat()
        }


class SourceDiscovery:
    """
    Kaynak keşif servisi
    
    Firecrawl /map ile site URL'lerini alır,
    PDF'leri filtreler, boyut bilgisi ekler.
    Sonuçları veritabanına kaydeder.
    """
    
    FIRECRAWL_MAP_URL = "https://api.firecrawl.dev/v1/map"
    
    def __init__(self, firecrawl_api_key: str = None, db=None):
        self.api_key = firecrawl_api_key or os.getenv("FIRECRAWL_API_KEY")
        self.db = db
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Cache - aynı domain tekrar taranmasın
        self._scanned_domains: Dict[str, datetime] = {}
        self._cache_hours = 24
    
    def _get_url_hash(self, url: str) -> str:
        """URL'den benzersiz hash oluştur"""
        normalized = url.lower().split("?")[0].split("#")[0]
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def save_discovered_pdf(self, pdf: 'DiscoveredPDF', brand: str = None, model: str = None, category: str = None) -> bool:
        """
        Keşfedilen PDF'i veritabanına kaydet (benzersiz)
        
        Returns:
            True: Yeni kayıt eklendi
            False: Zaten var (güncellendi)
        """
        if not self.db:
            return False
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            url_hash = self._get_url_hash(pdf.url)
            
            # Var mı kontrol et
            cursor.execute("SELECT id FROM discovered_pdfs WHERE url_hash = ?", (url_hash,))
            existing = cursor.fetchone()
            
            if existing:
                # Güncelle (last_checked)
                cursor.execute("""
                    UPDATE discovered_pdfs 
                    SET last_checked = CURRENT_TIMESTAMP,
                        size_bytes = COALESCE(?, size_bytes),
                        size_mb = COALESCE(?, size_mb)
                    WHERE url_hash = ?
                """, (pdf.size_bytes, pdf.size_mb, url_hash))
                conn.commit()
                conn.close()
                return False
            else:
                # Yeni kayıt
                cursor.execute("""
                    INSERT INTO discovered_pdfs 
                    (url_hash, url, title, domain, source_path, size_bytes, size_mb, brand, model, category, is_valid)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    url_hash, pdf.url, pdf.title, pdf.source_domain, pdf.source_path,
                    pdf.size_bytes, pdf.size_mb, brand, model, category, pdf.is_valid
                ))
                conn.commit()
                conn.close()
                return True
                
        except Exception as e:
            logger.error(f"PDF kaydetme hatası: {e}")
            return False
    
    def save_scanned_domain(self, domain: str, pdf_count: int) -> None:
        """Taranan domain'i kaydet"""
        if not self.db:
            return
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO scanned_domains (domain, total_pdfs, last_scanned)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(domain) DO UPDATE SET
                    total_pdfs = ?,
                    last_scanned = CURRENT_TIMESTAMP
            """, (domain, pdf_count, pdf_count))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Domain kaydetme hatası: {e}")
    
    def get_discovered_pdfs_count(self) -> int:
        """Toplam keşfedilen PDF sayısı"""
        if not self.db:
            return 0
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM discovered_pdfs")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except:
            return 0
    
    async def _ensure_session(self):
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=120)
            connector = aiohttp.TCPConnector(limit=100, limit_per_host=10)
            self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    # =========================================
    # DOMAIN EXTRACTION
    # =========================================
    
    def extract_domains_from_results(self, search_results: List[Dict]) -> List[SourceDomain]:
        """
        Arama sonuçlarından benzersiz domain'leri çıkar
        
        Args:
            search_results: Arama sonuçları listesi
            
        Returns:
            SourceDomain listesi (benzersiz)
        """
        domain_map: Dict[str, SourceDomain] = {}
        
        for result in search_results:
            url = result.get("url", "")
            if not url:
                continue
            
            try:
                parsed = urlparse(url)
                domain = parsed.netloc.lower().replace("www.", "")
                path = parsed.path
                
                # Domain'i ekle veya güncelle
                if domain not in domain_map:
                    domain_map[domain] = SourceDomain(domain=domain)
                
                # Path'i ekle (dosya adı hariç dizin kısmı)
                if "/" in path:
                    dir_path = "/".join(path.split("/")[:-1])
                    if dir_path and dir_path not in domain_map[domain].paths:
                        domain_map[domain].paths.append(dir_path)
                
                domain_map[domain].pdf_count += 1
                
            except Exception as e:
                logger.debug(f"URL parse error: {url} - {e}")
                continue
        
        # PDF sayısına göre sırala (çok bulunan önce)
        domains = list(domain_map.values())
        domains.sort(key=lambda x: x.pdf_count, reverse=True)
        
        return domains
    
    def _get_scan_paths(self, domain: str, paths: List[str]) -> List[str]:
        """
        Domain için taranacak path'leri oluştur (derinden başla)
        
        Örnek:
        Input: domain=example.com, paths=["/upload/user55/docs", "/catalog"]
        Output: [
            "https://example.com/upload/user55/docs/",
            "https://example.com/upload/user55/",
            "https://example.com/upload/",
            "https://example.com/catalog/",
            "https://example.com/"
        ]
        """
        scan_urls = set()
        
        for path in paths:
            # Path'i parçala ve her seviyeyi ekle
            parts = [p for p in path.split("/") if p]
            
            # Derinden yüzeye
            for i in range(len(parts), 0, -1):
                sub_path = "/" + "/".join(parts[:i]) + "/"
                full_url = f"https://{domain}{sub_path}"
                scan_urls.add(full_url)
        
        # Ana domain'i de ekle
        scan_urls.add(f"https://{domain}/")
        
        # Sırala (derin path'ler önce)
        sorted_urls = sorted(scan_urls, key=lambda x: -x.count("/"))
        
        return sorted_urls
    
    # =========================================
    # FIRECRAWL /MAP
    # =========================================
    
    async def _call_firecrawl_map(self, url: str) -> List[str]:
        """
        Firecrawl /map endpoint'ini çağır
        
        Args:
            url: Taranacak URL
            
        Returns:
            Bulunan URL listesi
        """
        if not self.api_key:
            logger.error("Firecrawl API key yok")
            return []
        
        await self._ensure_session()
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "url": url,
            "limit": 5000  # Max limit
        }
        
        try:
            async with self.session.post(
                self.FIRECRAWL_MAP_URL,
                headers=headers,
                json=payload
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    # Firecrawl yanıtı sürüme göre değişebiliyor:
                    # - {"links": [...]} veya {"data": {"links": [...]}}
                    raw_links = data.get("links")
                    if raw_links is None and isinstance(data.get("data"), dict):
                        raw_links = data["data"].get("links")
                    
                    if not isinstance(raw_links, list):
                        raw_links = []
                    
                    # Bazı sürümlerde liste elemanları dict olabilir: {"url": "..."}
                    links: List[str] = []
                    for item in raw_links:
                        if isinstance(item, str):
                            links.append(item)
                        elif isinstance(item, dict):
                            item_url = item.get("url") or item.get("link")
                            if isinstance(item_url, str) and item_url:
                                links.append(item_url)
                    
                    logger.info(f"Firecrawl map: {url} -> {len(links)} URL")
                    return links
                else:
                    error_text = await response.text()
                    logger.error(f"Firecrawl map error {response.status}: {error_text[:200]}")
                    return []
                    
        except Exception as e:
            logger.error(f"Firecrawl map exception: {e}")
            return []
    
    def _filter_pdf_urls(self, urls: List[str]) -> List[str]:
        """URL listesinden PDF'leri filtrele"""
        pdf_urls = []
        seen = set()
        
        for url in urls:
            # Normalize et (query string ve fragment kaldır)
            normalized = url.split("?")[0].split("#")[0].lower()
            
            # Sadece .pdf uzantılı dosyaları al
            if not normalized.endswith(".pdf"):
                continue
            
            # Duplicate kontrolü
            if normalized in seen:
                continue
            seen.add(normalized)
            
            pdf_urls.append(url)
        
        return pdf_urls
    
    # =========================================
    # HTTP HEAD - BOYUT KONTROLÜ
    # =========================================
    
    async def _get_pdf_size(self, url: str) -> Tuple[Optional[int], bool]:
        """
        HTTP HEAD ile PDF boyutunu al
        
        Returns:
            (size_bytes, is_valid)
        """
        await self._ensure_session()
        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            async with self.session.head(
                url,
                headers=headers,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    return None, False
                
                content_type = response.headers.get("Content-Type", "").lower()
                content_length = response.headers.get("Content-Length")
                
                is_pdf = "pdf" in content_type or url.lower().endswith(".pdf")
                size_bytes = int(content_length) if content_length else None
                
                return size_bytes, is_pdf
                
        except Exception as e:
            logger.debug(f"HEAD error {url}: {e}")
            return None, False
    
    async def _enrich_pdfs_with_size(
        self,
        pdfs: List[DiscoveredPDF],
        max_concurrent: int = 50,
        on_progress: callable = None
    ) -> List[DiscoveredPDF]:
        """
        PDF listesine boyut bilgisi ekle (paralel)
        
        Args:
            pdfs: PDF listesi
            max_concurrent: Eşzamanlı istek sayısı
            on_progress: Progress callback (current, total)
        """
        if not pdfs:
            return pdfs
        
        semaphore = asyncio.Semaphore(max_concurrent)
        completed = 0
        total = len(pdfs)
        
        async def fetch_size(pdf: DiscoveredPDF):
            nonlocal completed
            async with semaphore:
                size_bytes, is_valid = await self._get_pdf_size(pdf.url)
                pdf.size_bytes = size_bytes
                pdf.size_mb = size_bytes / (1024 * 1024) if size_bytes else None
                pdf.is_valid = is_valid
                
                completed += 1
                if on_progress and completed % 10 == 0:
                    await on_progress(completed, total)
        
        # Paralel çalıştır
        await asyncio.gather(*[fetch_size(pdf) for pdf in pdfs])
        
        if on_progress:
            await on_progress(total, total)
        
        return pdfs
    
    # =========================================
    # ANA TARAMA FONKSİYONU
    # =========================================
    
    async def scan_domain(
        self,
        domain: SourceDomain,
        on_progress: callable = None,
        on_pdfs_found: callable = None
    ) -> List[DiscoveredPDF]:
        """
        Tek domain'i tara
        
        Args:
            domain: Taranacak domain
            on_progress: Progress callback (status, progress, message)
            on_pdfs_found: PDF bulunduğunda callback (pdfs)
            
        Returns:
            Bulunan PDF listesi
        """
        all_pdfs: List[DiscoveredPDF] = []
        seen_urls: Set[str] = set()
        
        # Cache kontrolü
        cache_key = domain.domain
        if cache_key in self._scanned_domains:
            cache_time = self._scanned_domains[cache_key]
            if datetime.now() - cache_time < timedelta(hours=self._cache_hours):
                logger.info(f"Domain cached, skipping: {domain.domain}")
                domain.status = "cached"
                return []
        
        domain.status = "scanning"
        domain.progress = 0
        
        # Taranacak path'leri oluştur
        scan_urls = self._get_scan_paths(domain.domain, domain.paths)
        total_paths = len(scan_urls)
        
        if on_progress:
            await on_progress("scanning", 0, f"Taranıyor: {domain.domain}")
        
        try:
            for i, scan_url in enumerate(scan_urls):
                # Progress güncelle
                progress = int((i / total_paths) * 50)  # İlk %50 map için
                domain.progress = progress
                
                if on_progress:
                    await on_progress("scanning", progress, f"Map: {scan_url}")
                
                # Firecrawl /map çağır
                urls = await self._call_firecrawl_map(scan_url)
                
                # PDF'leri filtrele
                pdf_urls = self._filter_pdf_urls(urls)
                
                # Yeni PDF'leri ekle
                for pdf_url in pdf_urls:
                    normalized = pdf_url.lower().split("?")[0]
                    if normalized in seen_urls:
                        continue
                    seen_urls.add(normalized)
                    
                    # Başlık çıkar (URL'den)
                    title = pdf_url.split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ")
                    
                    pdf = DiscoveredPDF(
                        url=pdf_url,
                        title=title,
                        source_domain=domain.domain,
                        source_path=scan_url
                    )
                    all_pdfs.append(pdf)
                
                # Bulunan PDF'leri bildir
                if on_pdfs_found and pdf_urls:
                    new_count = len([u for u in pdf_urls if u.lower().split("?")[0] not in seen_urls])
                    if new_count > 0:
                        await on_pdfs_found(len(all_pdfs))
            
            # Boyut bilgisi ekle (%50-100)
            if all_pdfs:
                domain.progress = 50
                if on_progress:
                    await on_progress("enriching", 50, f"Boyut kontrolü: {len(all_pdfs)} PDF")
                
                async def size_progress(current, total):
                    progress = 50 + int((current / total) * 50)
                    domain.progress = progress
                    if on_progress:
                        await on_progress("enriching", progress, f"Boyut: {current}/{total}")
                
                all_pdfs = await self._enrich_pdfs_with_size(all_pdfs, on_progress=size_progress)
            
            # Veritabanına kaydet
            new_count = 0
            for pdf in all_pdfs:
                if self.save_discovered_pdf(pdf):
                    new_count += 1
            
            # Domain'i kaydet
            self.save_scanned_domain(domain.domain, len(all_pdfs))
            
            # Tamamlandı
            domain.status = "completed"
            domain.progress = 100
            domain.scanned_at = datetime.now()
            self._scanned_domains[cache_key] = datetime.now()
            
            if on_progress:
                await on_progress("completed", 100, f"Tamamlandı: {len(all_pdfs)} PDF ({new_count} yeni)")
            
            logger.info(f"Domain scan complete: {domain.domain} -> {len(all_pdfs)} PDFs ({new_count} new)")
            
        except Exception as e:
            domain.status = "error"
            domain.error_message = str(e)
            logger.error(f"Domain scan error: {domain.domain} - {e}")
            
            if on_progress:
                await on_progress("error", domain.progress, str(e))
        
        return all_pdfs
    
    async def scan_domain_stream(
        self,
        domain: SourceDomain
    ) -> AsyncGenerator[Dict, None]:
        """
        Domain taraması - SSE stream için generator
        
        Yields:
            {"type": "progress|pdf|complete|error", "data": ...}
        """
        all_pdfs: List[DiscoveredPDF] = []
        seen_urls: Set[str] = set()
        
        domain.status = "scanning"
        domain.progress = 0
        
        yield {"type": "progress", "data": {"status": "scanning", "progress": 0, "message": f"Başlatılıyor: {domain.domain}"}}
        
        scan_urls = self._get_scan_paths(domain.domain, domain.paths)
        total_paths = len(scan_urls)
        
        try:
            for i, scan_url in enumerate(scan_urls):
                progress = int((i / total_paths) * 50)
                domain.progress = progress
                
                yield {"type": "progress", "data": {"status": "scanning", "progress": progress, "message": f"Taranıyor: {scan_url}"}}
                
                urls = await self._call_firecrawl_map(scan_url)
                pdf_urls = self._filter_pdf_urls(urls)
                
                new_pdfs = []
                for pdf_url in pdf_urls:
                    normalized = pdf_url.lower().split("?")[0]
                    if normalized in seen_urls:
                        continue
                    seen_urls.add(normalized)
                    
                    title = pdf_url.split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ")
                    pdf = DiscoveredPDF(
                        url=pdf_url,
                        title=title,
                        source_domain=domain.domain,
                        source_path=scan_url
                    )
                    all_pdfs.append(pdf)
                    new_pdfs.append(pdf)
                
                # Yeni PDF'leri bildir
                if new_pdfs:
                    yield {"type": "pdfs", "data": {"count": len(new_pdfs), "total": len(all_pdfs), "pdfs": [p.to_dict() for p in new_pdfs]}}
            
            # Boyut kontrolü
            if all_pdfs:
                yield {"type": "progress", "data": {"status": "enriching", "progress": 50, "message": f"Boyut kontrolü: {len(all_pdfs)} PDF"}}
                
                # Batch olarak boyut al
                batch_size = 50
                for batch_start in range(0, len(all_pdfs), batch_size):
                    batch = all_pdfs[batch_start:batch_start + batch_size]
                    await self._enrich_pdfs_with_size(batch, max_concurrent=50)
                    
                    progress = 50 + int((batch_start + len(batch)) / len(all_pdfs) * 50)
                    domain.progress = progress
                    
                    yield {"type": "progress", "data": {"status": "enriching", "progress": progress, "message": f"Boyut: {batch_start + len(batch)}/{len(all_pdfs)}"}}
                    
                    # Boyutlu PDF'leri gönder
                    yield {"type": "pdfs_updated", "data": {"pdfs": [p.to_dict() for p in batch]}}
            
            # Veritabanına kaydet
            new_count = 0
            for pdf in all_pdfs:
                if self.save_discovered_pdf(pdf):
                    new_count += 1
            
            # Domain'i kaydet
            self.save_scanned_domain(domain.domain, len(all_pdfs))
            
            domain.status = "completed"
            domain.progress = 100
            domain.scanned_at = datetime.now()
            
            yield {"type": "complete", "data": {"total": len(all_pdfs), "new_count": new_count, "domain": domain.to_dict()}}
            
        except Exception as e:
            domain.status = "error"
            domain.error_message = str(e)
            yield {"type": "error", "data": {"message": str(e)}}


# Test
if __name__ == "__main__":
    async def test():
        discovery = SourceDiscovery()
        
        # Test domain extraction
        test_results = [
            {"url": "https://parts.example.com/upload/cat/ec210.pdf"},
            {"url": "https://parts.example.com/upload/cat/ec220.pdf"},
            {"url": "https://docs.other.com/manual.pdf"},
        ]
        
        domains = discovery.extract_domains_from_results(test_results)
        print(f"Found {len(domains)} domains:")
        for d in domains:
            print(f"  - {d.domain}: {d.pdf_count} PDFs, paths: {d.paths}")
        
        await discovery.close()
    
    asyncio.run(test())

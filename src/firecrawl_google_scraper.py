"""
Firecrawl + Google Scrape ile Premium Site Araması

Strateji:
1. Google URL oluştur: (site:scribd.com OR site:issuu.com OR ...) "arama terimi"
2. Firecrawl /scrape ile Google sayfasını çek (1 kredi)
3. Markdown'dan URL'leri parse et

Maliyet: 1 kredi = 8 siteden ~50-100 sonuç
Eski yöntem: 16 kredi = 80 sonuç

%94 TASARRUF!
"""
import asyncio
import aiohttp
import re
import hashlib
import os
from typing import List, Dict, Optional
from urllib.parse import quote, urlparse, unquote
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


# Premium siteler
PREMIUM_SITES = [
    "scribd.com",
    "issuu.com", 
    "manualzz.com",
    "pdfcoffee.com",
    "yumpu.com",
    "calameo.com",
    "slideshare.net",
    "academia.edu"
]


@dataclass
class PremiumResult:
    title: str
    url: str
    snippet: str
    domain: str
    platform: str
    query: str
    
    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "domain": self.domain,
            "platform": self.platform,
            "query": self.query,
            "engine": "firecrawl_google",
            "is_premium": True
        }


class FirecrawlGoogleScraper:
    """
    Firecrawl ile Google arama sonuçlarını scrape et
    
    Maliyet: 1 kredi / arama
    """
    
    BASE_URL = "https://api.firecrawl.dev/v1/scrape"
    
    # Document pattern'leri - gerçek doküman sayfalarını bulmak için
    DOC_PATTERNS = [
        "/document/", "/doc/", "/read/", "/publication/",
        "/book/", "/presentation/", "/paper/"
    ]
    
    def __init__(self, api_key: str, db=None):
        self.api_key = api_key
        self.db = db
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _ensure_session(self):
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=60)
            self.session = aiohttp.ClientSession(timeout=timeout)
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    def _build_google_url(self, search_terms: str, sites: List[str] = None, num: int = 100) -> str:
        """Google arama URL'i oluştur"""
        if sites is None:
            sites = PREMIUM_SITES
        
        # site:xxx.com OR site:yyy.com formatı
        site_query = " OR ".join([f"site:{site}" for site in sites])
        
        # Final sorgu: (site:scribd.com OR site:issuu.com) "volvo parts catalog"
        full_query = f'({site_query}) "{search_terms}"'
        
        # URL encode
        encoded_query = quote(full_query)
        
        return f"https://www.google.com/search?q={encoded_query}&num={num}"
    
    def _clean_url(self, url: str) -> str:
        """URL'den Google parametrelerini temizle"""
        # Fragment (#:~:text) temizle
        if "#" in url:
            url = url.split("#")[0]
        
        # Google translate parametrelerini temizle
        for param in ["&hl=", "&sl=", "&tl=", "&u="]:
            if param in url:
                url = url.split(param)[0]
        
        # Trailing slash düzelt
        if url.endswith("/"):
            url = url[:-1]
        
        return url
    
    def _extract_title_from_url(self, url: str) -> str:
        """URL'den title çıkar"""
        try:
            parsed = urlparse(url)
            path = parsed.path
            
            # Son segment'i al
            segments = [s for s in path.split("/") if s]
            if segments:
                last = segments[-1]
                # Dosya uzantısını çıkar
                if "." in last:
                    last = last.rsplit(".", 1)[0]
                # URL decode
                last = unquote(last)
                # Tire ve alt çizgileri boşluğa çevir
                last = last.replace("-", " ").replace("_", " ")
                # Title case
                return last.title()
        except:
            pass
        return ""
    
    def _is_real_document(self, url: str) -> bool:
        """URL gerçek bir doküman sayfası mı?"""
        url_lower = url.lower()
        
        # Google UI linklerini filtrele
        google_ui_patterns = [
            "/search?", "/preferences", "/setprefs", "/advanced_search",
            "google.com/url?", "/imgres?", "/maps", "/news"
        ]
        for pattern in google_ui_patterns:
            if pattern in url_lower:
                return False
        
        # Premium site mi?
        is_premium = any(site in url_lower for site in PREMIUM_SITES)
        if not is_premium:
            return False
        
        # Document path pattern kontrolü (daha yumuşak)
        # Scribd, issuu vb. genelde /document/, /doc/ gibi path'ler kullanır
        has_doc_pattern = any(pattern in url_lower for pattern in self.DOC_PATTERNS)
        
        # Eğer premium site ise ve ana sayfa değilse kabul et
        parsed = urlparse(url)
        if parsed.path and parsed.path != "/" and len(parsed.path) > 5:
            return True
        
        return has_doc_pattern
    
    def _parse_markdown_results(self, markdown: str, query: str) -> List[PremiumResult]:
        """Google markdown çıktısından URL'leri parse et"""
        results = []
        seen_urls = set()
        
        # Markdown'daki tüm linkleri bul: [title](url)
        link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        matches = re.findall(link_pattern, markdown)
        
        for title, url in matches:
            # URL temizle
            url = self._clean_url(url)
            
            # Gerçek doküman mı kontrol et
            if not self._is_real_document(url):
                continue
            
            # Normalize URL for duplicate check
            normalized = url.lower().rstrip("/")
            if "?" in normalized:
                normalized = normalized.split("?")[0]
            
            if normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            
            # Domain bul
            domain = ""
            for site in PREMIUM_SITES:
                if site in url.lower():
                    domain = site
                    break
            
            if not domain:
                continue
            
            # Platform ismi
            platform = domain.split(".")[0].title()
            
            # Title yoksa URL'den çıkar
            if not title or title == url or len(title) < 3:
                title = self._extract_title_from_url(url)
            
            results.append(PremiumResult(
                title=title[:500] if title else "",
                url=url,
                snippet="",
                domain=domain,
                platform=platform,
                query=query
            ))
        
        # Alternatif: Düz URL'leri de bul
        url_pattern = r'(https?://(?:www\.)?(?:' + '|'.join([re.escape(s) for s in PREMIUM_SITES]) + r')[^\s\)]+)'
        url_matches = re.findall(url_pattern, markdown, re.IGNORECASE)
        
        for url in url_matches:
            url = self._clean_url(url)
            
            normalized = url.lower().rstrip("/")
            if "?" in normalized:
                normalized = normalized.split("?")[0]
            
            if normalized in seen_urls:
                continue
            
            if not self._is_real_document(url):
                continue
            
            seen_urls.add(normalized)
            
            # Domain bul
            domain = ""
            for site in PREMIUM_SITES:
                if site in url.lower():
                    domain = site
                    break
            
            if domain:
                platform = domain.split(".")[0].title()
                results.append(PremiumResult(
                    title=self._extract_title_from_url(url),
                    url=url,
                    snippet="",
                    domain=domain,
                    platform=platform,
                    query=query
                ))
        
        return results
    
    async def search_premium_sites(
        self, 
        search_terms: str, 
        sites: List[str] = None,
        num_results: int = 100
    ) -> Dict:
        """
        Tüm premium sitelerde arama yap
        
        Args:
            search_terms: Arama terimleri (örnek: "volvo ec210 parts catalog")
            sites: Hangi siteler (None = hepsi)
            num_results: Google'dan kaç sonuç (max 100)
        
        Returns:
            {"results": [...], "stats": {...}}
        
        Maliyet: 1 kredi
        """
        if not self.api_key:
            logger.error("Firecrawl API key yok")
            return {"results": [], "stats": {"error": "No API key"}}
        
        await self._ensure_session()
        
        # Google URL oluştur
        google_url = self._build_google_url(search_terms, sites, num_results)
        logger.info(f"Google URL: {google_url[:100]}...")
        
        # Firecrawl /scrape ile çek
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "url": google_url,
            "formats": ["markdown"]
        }
        
        try:
            async with self.session.post(self.BASE_URL, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    markdown = data.get("data", {}).get("markdown", "")
                    
                    if not markdown:
                        logger.warning("Boş markdown döndü")
                        return {"results": [], "stats": {"error": "Empty markdown"}}
                    
                    # Parse et
                    results = self._parse_markdown_results(markdown, search_terms)
                    result_dicts = [r.to_dict() for r in results]
                    
                    # İstatistikler
                    by_site = {}
                    for r in result_dicts:
                        domain = r["domain"]
                        if domain not in by_site:
                            by_site[domain] = 0
                        by_site[domain] += 1
                    
                    stats = {
                        "total": len(result_dicts),
                        "by_site": by_site,
                        "credits_used": 1,
                        "method": "firecrawl_google_scrape"
                    }
                    
                    logger.info(f"Premium Google scrape: {stats['total']} sonuç, 1 kredi")
                    
                    # Veritabanına kaydet
                    if self.db:
                        self._save_results(result_dicts)
                    
                    return {"results": result_dicts, "stats": stats}
                
                else:
                    error_text = await response.text()
                    logger.error(f"Firecrawl hata {response.status}: {error_text}")
                    return {"results": [], "stats": {"error": error_text}}
                    
        except Exception as e:
            logger.error(f"Firecrawl istek hatası: {e}")
            return {"results": [], "stats": {"error": str(e)}}
    
    def _save_results(self, results: List[Dict]) -> int:
        """Sonuçları veritabanına kaydet"""
        if not self.db or not results:
            return 0
        
        saved = 0
        
        try:
            conn = self.db.get_connection()
            for r in results:
                url_hash = hashlib.md5(r['url'].encode()).hexdigest()
                cursor = conn.execute(
                    "SELECT id FROM premium_results WHERE url_hash = ?", 
                    (url_hash,)
                )
                
                if cursor.fetchone():
                    conn.execute("""
                        UPDATE premium_results 
                        SET last_seen = datetime('now'), view_count = view_count + 1 
                        WHERE url_hash = ?
                    """, (url_hash,))
                else:
                    conn.execute("""
                        INSERT INTO premium_results 
                        (url_hash, url, title, snippet, platform, domain, query)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        url_hash, r['url'], r.get('title', '')[:500],
                        r.get('snippet', '')[:1000], r.get('platform', ''),
                        r.get('domain', ''), r.get('query', '')
                    ))
                    saved += 1
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Kayıt hatası: {e}")
        
        return saved


# Test fonksiyonu
async def test_google_scrape():
    """Test"""
    api_key = os.getenv("FIRECRAWL_API_KEY")
    
    if not api_key:
        print("FIRECRAWL_API_KEY gerekli!")
        return
    
    scraper = FirecrawlGoogleScraper(api_key)
    
    result = await scraper.search_premium_sites("volvo ec210 parts catalog")
    
    print(f"\n{'='*60}")
    print(f"SONUÇLAR")
    print(f"{'='*60}")
    print(f"Toplam: {result['stats'].get('total', 0)}")
    print(f"Site bazlı: {result['stats'].get('by_site', {})}")
    print(f"Kredi: {result['stats'].get('credits_used', 0)}")
    
    print(f"\nİlk 10 sonuç:")
    for i, r in enumerate(result['results'][:10], 1):
        print(f"{i}. [{r['platform']}] {r['title'][:50] or r['url'][:50]}...")
    
    await scraper.close()
    
    return result


if __name__ == "__main__":
    asyncio.run(test_google_scrape())

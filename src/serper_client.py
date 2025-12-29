import os
import asyncio
import aiohttp
from typing import List, Dict, Optional
from dataclasses import dataclass
from urllib.parse import urlparse
from datetime import datetime
import logging
from src.keywords import EXCLUDED_DOMAINS

logger = logging.getLogger(__name__)

@dataclass
class SearchResult:
    """Arama sonucu veri yapısı"""
    title: str
    url: str
    snippet: str
    position: int
    query: str
    language: str
    is_pdf: bool
    domain: str
    discovered_at: str = None
    
    def __post_init__(self):
        if not self.discovered_at:
            self.discovered_at = datetime.now().isoformat()
        self.domain = urlparse(self.url).netloc
        self.is_pdf = '.pdf' in self.url.lower()


from src.config import SERPER_API_KEY

def _get_serper_key_from_db():
    """Veritabanından Serper API anahtarını al"""
    try:
        from src.settings_manager import get_settings_manager
        settings = get_settings_manager()
        keys = settings.get_search_api_keys()
        return keys.get("serper", "")
    except Exception:
        return ""

class SerperClient:
    """Serper.dev API Client - Gelişmiş"""
    
    BASE_URL = "https://google.serper.dev"
    
    def __init__(self, api_key: str = None):
        # Öncelik: parametre > env > veritabanı > config fallback
        self.api_key = api_key or os.getenv('SERPER_API_KEY') or _get_serper_key_from_db() or SERPER_API_KEY
        # API key yoksa uyarı ver ama hata fırlatma (lazy check)
        
        self.headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.request_count = 0
    
    async def _ensure_session(self):
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def __aenter__(self):
        await self._ensure_session()
        return self
    
    async def __aexit__(self, *args):
        await self.close()

    async def search(self, query: str, search_type: str = "search", num: int = 10, gl: str = "us", hl: str = "en", **kwargs) -> Dict:
        # API key kontrolü
        if not self.api_key:
            logger.error("Serper API key yapılandırılmamış")
            return {"organic": [], "error": "API key not configured"}
        
        await self._ensure_session()
        
        url = f"{self.BASE_URL}/{search_type}"
        payload = {
            "q": query,
            "num": min(num, 100),
            "gl": gl,
            "hl": hl,
            **kwargs
        }
        
        try:
            async with self.session.post(url, headers=self.headers, json=payload) as response:
                self.request_count += 1
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Serper API Hatası {response.status}: {error_text}")
                    return {"organic": [], "error": error_text}
        except Exception as e:
            logger.error(f"İstek hatası: {e}")
            return {"organic": [], "error": str(e)}

    async def search_pdfs(self, query: str, num: int = 30, gl: str = "us", hl: str = "en") -> List[SearchResult]:
        """
        PDF dosyaları için özelleştirilmiş arama
        
        Serper API tek seferde max 10 sonuç döndürür.
        Pagination ile istenen sayıda sonuç toplanır.
        """
        # filetype:pdf ekle - daha kesin sonuçlar için
        if 'filetype:pdf' not in query.lower() and 'pdf' not in query.lower():
            query = f"{query} filetype:pdf"
        
        results = []
        seen_urls = set()
        page = 1
        max_pages = min((num // 10) + 1, 10)  # Max 10 sayfa (100 sonuç)
        
        # Debug log (production'da kaldır)
        # print(f"[SERPER] Query: {query}, Hedef: {num}, Max sayfa: {max_pages}")
        
        while len(results) < num and page <= max_pages:
            # Serper'da page parametresi kullanılıyor
            data = await self.search(query, num=10, gl=gl, hl=hl, page=page)
            
            organic = data.get('organic', [])
            if not organic:
                break  # Daha fazla sonuç yok
            
            for i, item in enumerate(organic):
                url = item.get('link', '')
                
                # Duplicate kontrolü
                url_clean = url.lower().split('?')[0]
                if url_clean in seen_urls:
                    continue
                seen_urls.add(url_clean)
                
                title = item.get('title', '').lower()
                snippet = item.get('snippet', '').lower()
                
                # PDF kontrolü - URL, title veya snippet'te pdf geçmeli
                is_pdf = '.pdf' in url.lower() or 'pdf' in title or 'pdf' in snippet
                
                if is_pdf:
                    domain = urlparse(url).netloc
                    if not any(excluded in domain for excluded in EXCLUDED_DOMAINS):
                        results.append(SearchResult(
                            title=item.get('title', ''),
                            url=url,
                            snippet=item.get('snippet', ''),
                            position=len(results) + 1,
                            query=query,
                            language=hl,
                            is_pdf=True,
                            domain=domain
                        ))
                        
                        if len(results) >= num:
                            break
            
            page += 1
        
        # print(f"[SERPER] Toplam: {len(results)} sonuç ({page-1} sayfa)")
        return results

    async def search_general(self, query: str, num: int = 20, gl: str = "us", hl: str = "en", start: int = 0) -> List[SearchResult]:
        """Genel arama - Premium platformlar için (PDF filtresi olmadan)"""
        # start parametresi ile sayfalama
        kwargs = {}
        if start > 0:
            kwargs['start'] = start
        data = await self.search(query, num=num, gl=gl, hl=hl, **kwargs)
        
        results = []
        for i, item in enumerate(data.get('organic', [])):
            url = item.get('link', '')
            domain = urlparse(url).netloc
            
            # Excluded domain kontrolü
            if not any(excluded in domain for excluded in EXCLUDED_DOMAINS):
                results.append(SearchResult(
                    title=item.get('title', ''),
                    url=url,
                    snippet=item.get('snippet', ''),
                    position=i + 1,
                    query=query,
                    language=hl,
                    is_pdf='.pdf' in url.lower(),
                    domain=domain
                ))
        return results


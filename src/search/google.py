"""
Google/Serper Search API Client
https://serper.dev/
"""
import os
import asyncio
import aiohttp
from typing import List, Dict, Optional
from dataclasses import dataclass
from urllib.parse import urlparse
from datetime import datetime
import logging

from src.data.domains import is_excluded_domain

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


def _get_serper_key_from_db() -> str:
    """Veritabanından Serper API anahtarını al"""
    try:
        from src.settings_manager import get_settings_manager
        settings = get_settings_manager()
        keys = settings.get_search_api_keys()
        return keys.get("serper", "")
    except Exception:
        return ""


class GoogleSearchClient:
    """Serper.dev API Client - Google arama sonuçları"""
    
    BASE_URL = "https://google.serper.dev"
    MAX_RESULTS_PER_REQUEST = 100
    
    def __init__(self, api_key: str = None):
        from src.config import SERPER_API_KEY
        # Öncelik: parametre > env > veritabanı > config fallback
        self.api_key = api_key or os.getenv('SERPER_API_KEY') or _get_serper_key_from_db() or SERPER_API_KEY
        
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

    async def search(
        self, 
        query: str, 
        search_type: str = "search", 
        num: int = 10, 
        gl: str = "us", 
        hl: str = "en", 
        **kwargs
    ) -> Dict:
        """
        Serper API ile arama yap
        
        Args:
            query: Arama sorgusu
            search_type: Arama tipi (search, news, images)
            num: Sonuç sayısı (max 100)
            gl: Ülke kodu
            hl: Dil kodu
        """
        if not self.api_key:
            logger.error("Serper API key yapılandırılmamış")
            return {"organic": [], "error": "API key not configured"}
        
        await self._ensure_session()
        
        url = f"{self.BASE_URL}/{search_type}"
        payload = {
            "q": query,
            "num": min(num, self.MAX_RESULTS_PER_REQUEST),
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

    async def search_pdfs(
        self, 
        query: str, 
        count: int = 50, 
        language: str = "en"
    ) -> List[Dict]:
        """
        PDF dosyaları için arama yap
        
        Args:
            query: Arama sorgusu (filetype:pdf içermelidir)
            count: İstenilen sonuç sayısı (max 50)
            language: Dil kodu
        
        Returns:
            PDF sonuç listesi
        """
        # Sorgu zaten filetype:pdf içermeli (query_builder'dan geliyor)
        
        data = await self.search(query, num=min(count, 50), hl=language)
        
        results = []
        for i, item in enumerate(data.get('organic', [])):
            url = item.get('link', '')
            title = item.get('title', '').lower()
            snippet = item.get('snippet', '').lower()
            
            # PDF kontrolü - URL, title veya snippet'te pdf geçmeli
            # Sorgu zaten filetype:pdf içeriyor, bu yüzden esnek kontrol yeterli
            is_pdf = (
                '.pdf' in url.lower() or 
                'pdf' in title or
                '[pdf]' in title or
                'pdf' in snippet
            )
            
            if not is_pdf:
                continue
            
            # Hariç tutulan domain kontrolü
            if is_excluded_domain(url):
                continue
            
            results.append({
                "title": item.get('title', ''),
                "url": url,
                "description": item.get('snippet', ''),
                "source": "google",
                "language": language,
                "position": i + 1
            })
        
        return results[:count]

    async def search_general(
        self, 
        query: str, 
        count: int = 20, 
        language: str = "en", 
        start: int = 0
    ) -> List[SearchResult]:
        """Genel arama - PDF filtresi olmadan"""
        kwargs = {}
        if start > 0:
            kwargs['start'] = start
        
        data = await self.search(query, num=count, hl=language, **kwargs)
        
        results = []
        for i, item in enumerate(data.get('organic', [])):
            url = item.get('link', '')
            domain = urlparse(url).netloc
            
            if not is_excluded_domain(url):
                results.append(SearchResult(
                    title=item.get('title', ''),
                    url=url,
                    snippet=item.get('snippet', ''),
                    position=i + 1,
                    query=query,
                    language=language,
                    is_pdf='.pdf' in url.lower(),
                    domain=domain
                ))
        
        return results


# Geriye uyumluluk için alias
SerperClient = GoogleSearchClient


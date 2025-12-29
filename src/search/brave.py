"""
Brave Search API Client
https://api.search.brave.com/
"""
import os
import aiohttp
from typing import List, Dict, Optional, Any
import logging

from src.data.domains import is_excluded_domain

logger = logging.getLogger(__name__)


def _get_brave_key_from_db() -> str:
    """Veritabanından Brave API anahtarını al"""
    try:
        from src.settings_manager import get_settings_manager
        settings = get_settings_manager()
        keys = settings.get_search_api_keys()
        return keys.get("brave", "")
    except Exception:
        return ""


class BraveSearchClient:
    """Brave Search API istemcisi"""
    
    BASE_URL = "https://api.search.brave.com/res/v1/web/search"
    MAX_RESULTS_PER_REQUEST = 20  # Brave limiti
    
    def __init__(self, api_key: str = None):
        from src.config import BRAVE_API_KEY
        # Öncelik: parametre > env > veritabanı > config fallback
        self.api_key = api_key or os.getenv('BRAVE_API_KEY') or _get_brave_key_from_db() or BRAVE_API_KEY
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def search(
        self,
        query: str,
        count: int = 20,
        offset: int = 0,
        country: str = "US",
        language: str = "en",
        freshness: str = None
    ) -> Dict[str, Any]:
        """
        Brave Search API ile arama yap
        
        Args:
            query: Arama sorgusu
            count: Sonuç sayısı (max 20)
            offset: Sayfalama offset
            country: Ülke kodu
            language: Dil kodu
            freshness: Zaman filtresi
        """
        await self._ensure_session()
        
        # Brave API dil kodu dönüşümü
        BRAVE_LANG_MAP = {
            "zh": "zh-hans",
            "ja": "jp",
            "ko": "ko",
            "ar": "ar",
        }
        brave_lang = BRAVE_LANG_MAP.get(language, language)
        
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key
        }
        
        params = {
            "q": query,
            "count": min(count, self.MAX_RESULTS_PER_REQUEST),
            "offset": offset,
            "country": country,
            "search_lang": brave_lang,
            "text_decorations": "false"
        }
        
        if freshness:
            params["freshness"] = freshness
        
        try:
            async with self._session.get(self.BASE_URL, headers=headers, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Brave API error {response.status}: {error_text}")
                    return {"error": error_text, "status": response.status}
        except Exception as e:
            logger.error(f"Brave API request failed: {e}")
            return {"error": str(e)}
    
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
        """
        results = []
        offset = 0
        
        # Sayfalama ile daha fazla sonuç al (max 200 sonuç kontrol et)
        while len(results) < count and offset < 200:
            response = await self.search(
                query=query,
                count=min(20, count - len(results)),
                offset=offset,
                language=language
            )
            
            if "error" in response:
                break
            
            web_results = response.get("web", {}).get("results", [])
            
            if not web_results:
                break
            
            for item in web_results:
                url = item.get("url", "")
                title = item.get("title", "").lower()
                desc = item.get("description", "").lower()
                
                # PDF kontrolü - URL, title veya description'da pdf geçmeli
                # Sorgu zaten filetype:pdf içeriyor, bu yüzden daha esnek kontrol
                is_pdf = (
                    url.lower().endswith(".pdf") or 
                    ".pdf" in url.lower() or
                    "pdf" in title or
                    "[pdf]" in title or
                    "pdf" in desc
                )
                
                if not is_pdf:
                    continue
                
                # Hariç tutulan domain kontrolü
                if is_excluded_domain(url):
                    continue
                
                results.append({
                    "title": item.get("title", ""),
                    "url": url,
                    "description": item.get("description", ""),
                    "source": "brave",
                    "language": language
                })
            
            offset += 20
            
            # Daha fazla sonuç yoksa çık
            if len(web_results) < 20:
                break
        
        return results[:count]
    
    async def search_site(
        self,
        domain: str,
        query: str = "",
        count: int = 20
    ) -> List[Dict]:
        """
        Belirli bir sitede arama yap
        
        Args:
            domain: Site domain'i
            query: Ek arama sorgusu
            count: İstenilen sonuç sayısı
        """
        site_query = f"site:{domain}"
        if query:
            site_query += f" {query}"
        site_query += " filetype:pdf"
        
        results = []
        offset = 0
        
        while len(results) < count:
            response = await self.search(
                query=site_query,
                count=min(20, count - len(results)),
                offset=offset
            )
            
            if "error" in response:
                break
            
            web_results = response.get("web", {}).get("results", [])
            
            if not web_results:
                break
            
            for item in web_results:
                if not is_excluded_domain(item.get("url", "")):
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "description": item.get("description", ""),
                        "source": "brave"
                    })
            
            offset += 20
            
            if len(web_results) < 20:
                break
        
        return results[:count]


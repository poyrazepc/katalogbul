"""
SearchApi.io Client
https://www.searchapi.io/
Supports: Bing, Baidu, Google, and more
"""
import os
import aiohttp
from typing import List, Dict, Optional, Any

from src.config import SEARCHAPI_KEY


def _get_searchapi_key_from_db():
    """Veritabanından SearchAPI anahtarını al"""
    try:
        from src.settings_manager import get_settings_manager
        settings = get_settings_manager()
        keys = settings.get_search_api_keys()
        return keys.get("searchapi", "")
    except Exception:
        return ""


class SearchApiClient:
    """SearchApi.io istemcisi - Bing, Baidu ve diğer motorlar"""
    
    BASE_URL = "https://www.searchapi.io/api/v1/search"
    
    def __init__(self, api_key: str = None):
        # Öncelik: parametre > env > veritabanı > config fallback
        self.api_key = api_key or os.getenv('SEARCHAPI_KEY') or _get_searchapi_key_from_db() or SEARCHAPI_KEY
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
        engine: str = "bing",
        num: int = 20,
        page: int = 1,
        country: str = None,
        language: str = None
    ) -> Dict[str, Any]:
        """
        SearchApi.io ile arama yap
        
        Args:
            query: Arama sorgusu
            engine: Arama motoru (bing, baidu, google, yandex, etc.)
            num: Sonuç sayısı
            page: Sayfa numarası
            country: Ülke kodu
            language: Dil kodu
        """
        await self._ensure_session()
        
        params = {
            "api_key": self.api_key,
            "engine": engine,
            "q": query,
            "num": num,
            "page": page
        }
        
        if country:
            params["country"] = country
        if language:
            params["hl"] = language
        
        try:
            async with self._session.get(self.BASE_URL, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    print(f"SearchApi error {response.status}: {error_text}")
                    return {"error": error_text, "status": response.status}
        except Exception as e:
            print(f"SearchApi request failed: {e}")
            return {"error": str(e)}
    
    async def search_pdfs(
        self,
        query: str,
        engine: str = "bing",
        count: int = 20,
        language: str = "en"
    ) -> List[Dict]:
        """
        PDF dosyaları için arama yap
        
        Args:
            query: Arama sorgusu
            engine: Arama motoru
            count: İstenilen sonuç sayısı
            language: Dil kodu
        """
        # PDF araması için sorguyu düzenle
        if engine == "bing":
            pdf_query = f"{query} filetype:pdf"
        elif engine == "baidu":
            pdf_query = f"{query} filetype:pdf"
        elif engine == "naver":
            # Naver PDF araması
            pdf_query = f"{query} pdf"
        else:
            pdf_query = f"{query} pdf"
        
        results = []
        page = 1
        max_pages = 5
        
        while len(results) < count and page <= max_pages:
            response = await self.search(
                query=pdf_query,
                engine=engine,
                num=min(20, count - len(results)),
                page=page,
                language=language
            )
            
            if "error" in response:
                break
            
            # Organic results
            organic_results = response.get("organic_results", [])
            
            if not organic_results:
                break
            
            for item in organic_results:
                url = item.get("link", "") or item.get("url", "")
                
                # PDF URL'lerini filtrele
                if url.lower().endswith(".pdf") or "pdf" in url.lower():
                    results.append({
                        "title": item.get("title", ""),
                        "url": url,
                        "description": item.get("snippet", "") or item.get("description", ""),
                        "source": f"searchapi_{engine}",
                        "language": language
                    })
            
            page += 1
            
            if len(organic_results) < 10:
                break
        
        return results[:count]
    
    async def search_bing(self, query: str, count: int = 20, language: str = "en") -> List[Dict]:
        """Bing ile PDF arama"""
        return await self.search_pdfs(query, engine="bing", count=count, language=language)
    
    async def search_baidu(self, query: str, count: int = 20) -> List[Dict]:
        """Baidu ile PDF arama (Çince için optimize)"""
        return await self.search_pdfs(query, engine="baidu", count=count, language="zh")
    
    async def search_naver(self, query: str, count: int = 20) -> List[Dict]:
        """Naver ile PDF arama (Korece için optimize)"""
        return await self.search_pdfs(query, engine="naver", count=count, language="ko")
    
    async def search_site(
        self,
        domain: str,
        query: str = "",
        engine: str = "bing",
        count: int = 20
    ) -> List[Dict]:
        """
        Belirli bir sitede arama yap
        
        Args:
            domain: Site domain'i
            query: Ek arama sorgusu
            engine: Arama motoru
            count: İstenilen sonuç sayısı
        """
        site_query = f"site:{domain} filetype:pdf"
        if query:
            site_query = f"{query} {site_query}"
        
        results = []
        page = 1
        
        while len(results) < count and page <= 5:
            response = await self.search(
                query=site_query,
                engine=engine,
                num=min(20, count - len(results)),
                page=page
            )
            
            if "error" in response:
                break
            
            organic_results = response.get("organic_results", [])
            
            for item in organic_results:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", "") or item.get("url", ""),
                    "description": item.get("snippet", "") or item.get("description", ""),
                    "source": f"searchapi_{engine}"
                })
            
            page += 1
            
            if not organic_results:
                break
        
        return results[:count]


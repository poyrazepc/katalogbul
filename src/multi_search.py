"""
Multi-Engine Search Coordinator
Tüm arama motorlarını koordine eden ana sınıf
"""
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime

from src.config import SEARCH_ENGINES
from src.cache_manager import CacheManager
from src.serper_client import SerperClient
from src.brave_client import BraveSearchClient
from src.yandex_client import YandexSearchClient
from src.searchapi_client import SearchApiClient


class MultiSearchCoordinator:
    """Çoklu arama motoru koordinatörü"""
    
    def __init__(self, use_cache: bool = True):
        self.use_cache = use_cache
        self.cache = CacheManager() if use_cache else None
        
        # Arama motorları istemcileri
        self.serper = SerperClient()
        self.brave = BraveSearchClient()
        self.searchapi = SearchApiClient()
        
        # Yandex client optional (authorized_key.json olmayabilir)
        try:
            self.yandex = YandexSearchClient()
        except Exception as e:
            print(f"Yandex client başlatılamadı: {e}")
            self.yandex = None
        
        # Aktif motorlar
        self.engines = {
            "serper": self.serper,
            "brave": self.brave,
            "searchapi_bing": self.searchapi,
            "searchapi_google": self.searchapi,
            "searchapi_baidu": self.searchapi,
            "searchapi_naver": self.searchapi
        }
        if self.yandex:
            self.engines["yandex"] = self.yandex
    
    async def close(self):
        """Tüm session'ları kapat"""
        await self.serper.close()
        await self.brave.close()
        if self.yandex:
            await self.yandex.close()
        await self.searchapi.close()
    
    async def search_single_engine(
        self,
        engine_name: str,
        query: str,
        count: int = 20,
        language: str = "en",
        doc_type: str = None,
        use_cache: bool = True,
        page: int = None
    ) -> Dict[str, Any]:
        """
        Tek bir motor ile arama yap - sayfa bazlı cache
        
        Returns:
            {
                "engine": str,
                "results": List[Dict],
                "count": int,
                "cached": bool,
                "error": str or None
            }
        """
        # Cache kontrolü - sayfa bazlı
        if self.use_cache and use_cache:
            cached_results = self.cache.get_cached_results(
                engine=engine_name,
                query=query,
                language=language,
                doc_type=doc_type,
                page=page
            )
            if cached_results is not None:
                return {
                    "engine": engine_name,
                    "engine_name": SEARCH_ENGINES.get(engine_name, {}).get("name", engine_name),
                    "results": cached_results,
                    "count": len(cached_results),
                    "cached": True,
                    "error": None
                }
        
        # API'den ara
        results = []
        error = None
        
        try:
            if engine_name == "serper":
                results = await self.serper.search_pdfs(query, num=count, hl=language)
                # SearchResult -> dict dönüşümü
                results = [{"title": r.title, "url": r.url, "description": r.snippet, "source": "serper", "language": language} for r in results]
            elif engine_name == "brave":
                results = await self.brave.search_pdfs(query, count=count, language=language)
            elif engine_name == "yandex":
                results = await self.yandex.search_pdfs(query, count=count, language=language)
            elif engine_name == "searchapi_bing":
                # Bing ile ara
                results = await self.searchapi.search_pdfs(query, engine="bing", count=count, language=language)
            elif engine_name == "searchapi_google":
                # Google ile ara (SearchApi.io üzerinden)
                results = await self.searchapi.search_pdfs(query, engine="google", count=count, language=language)
            elif engine_name == "searchapi_baidu":
                # Baidu ile ara (Çin için)
                results = await self.searchapi.search_baidu(query, count=count)
            elif engine_name == "searchapi_naver":
                # Naver ile ara (Kore için)
                results = await self.searchapi.search_naver(query, count=count)
        except Exception as e:
            error = str(e)
            print(f"Error searching {engine_name}: {e}")
        
        # Cache'e kaydet - sayfa bazlı
        if self.use_cache and results and not error:
            self.cache.save_to_cache(
                engine=engine_name,
                query=query,
                results=results,
                language=language,
                doc_type=doc_type,
                page=page
            )
        
        return {
            "engine": engine_name,
            "engine_name": SEARCH_ENGINES.get(engine_name, {}).get("name", engine_name),
            "results": results,
            "count": len(results),
            "cached": False,
            "error": error
        }
    
    async def search_all_engines(
        self,
        query: str,
        count_per_engine: int = 20,
        language: str = "en",
        doc_type: str = None,
        engines: List[str] = None,
        use_cache: bool = True,
        page: int = None
    ) -> Dict[str, Any]:
        """
        Tüm motorlarla paralel arama yap - sayfa bazlı cache
        
        Args:
            query: Arama sorgusu
            count_per_engine: Her motor için sonuç sayısı
            language: Dil kodu
            doc_type: Döküman tipi
            engines: Kullanılacak motorlar (None = hepsi)
            use_cache: Cache kullan
            page: Sayfa numarası (cache key için)
            
        Returns:
            {
                "query": str,
                "language": str,
                "engines": {
                    "serper": {...},
                    "brave": {...},
                    ...
                },
                "total_results": int,
                "merged_results": List[Dict],
                "search_time": float
            }
        """
        start_time = datetime.now()
        
        # Hangi motorları kullanacağız (None veya boş liste ise tüm aktif motorları kullan)
        if not engines:
            engines = [name for name, config in SEARCH_ENGINES.items() if config.get("enabled", True)]
        
        # Paralel arama görevleri
        tasks = []
        for engine_name in engines:
            if engine_name in self.engines:
                task = self.search_single_engine(
                    engine_name=engine_name,
                    query=query,
                    count=count_per_engine,
                    language=language,
                    doc_type=doc_type,
                    use_cache=use_cache,
                    page=page
                )
                tasks.append(task)
        
        # Paralel çalıştır
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Sonuçları düzenle
        engine_results = {}
        all_results = []
        
        for result in results:
            if isinstance(result, Exception):
                print(f"Search exception: {result}")
                continue
            
            engine_name = result.get("engine")
            engine_results[engine_name] = result
            
            # Sonuçları birleştir
            for item in result.get("results", []):
                item["engine"] = engine_name
                all_results.append(item)
        
        # Duplicate URL'leri kaldır (ilk bulunanı tut)
        seen_urls = set()
        merged_results = []
        for item in all_results:
            url = item.get("url", "").lower()
            if url not in seen_urls:
                seen_urls.add(url)
                merged_results.append(item)
        
        search_time = (datetime.now() - start_time).total_seconds()
        
        return {
            "query": query,
            "language": language,
            "doc_type": doc_type,
            "engines": engine_results,
            "total_results": len(merged_results),
            "merged_results": merged_results,
            "search_time": search_time
        }
    
    async def search_site_all_engines(
        self,
        domain: str,
        query: str = "",
        count_per_engine: int = 20,
        engines: List[str] = None
    ) -> Dict[str, Any]:
        """
        Tüm motorlarla belirli bir sitede arama yap
        """
        start_time = datetime.now()
        
        if engines is None:
            engines = [name for name, config in SEARCH_ENGINES.items() if config.get("enabled", True)]
        
        tasks = []
        for engine_name in engines:
            if engine_name == "serper":
                task = asyncio.create_task(self._search_site_serper(domain, query, count_per_engine))
            elif engine_name == "brave":
                task = asyncio.create_task(self.brave.search_site(domain, query, count_per_engine))
            elif engine_name == "yandex":
                task = asyncio.create_task(self.yandex.search_site(domain, query, count_per_engine))
            elif engine_name == "searchapi":
                task = asyncio.create_task(self.searchapi.search_site(domain, query, "bing", count_per_engine))
            else:
                continue
            tasks.append((engine_name, task))
        
        # Sonuçları topla
        engine_results = {}
        all_results = []
        
        for engine_name, task in tasks:
            try:
                results = await task
                engine_results[engine_name] = {
                    "engine": engine_name,
                    "engine_name": SEARCH_ENGINES.get(engine_name, {}).get("name", engine_name),
                    "results": results,
                    "count": len(results)
                }
                for item in results:
                    item["engine"] = engine_name
                    all_results.append(item)
            except Exception as e:
                engine_results[engine_name] = {
                    "engine": engine_name,
                    "results": [],
                    "count": 0,
                    "error": str(e)
                }
        
        # Duplicate kaldır
        seen_urls = set()
        merged_results = []
        for item in all_results:
            url = item.get("url", "").lower()
            if url not in seen_urls:
                seen_urls.add(url)
                merged_results.append(item)
        
        search_time = (datetime.now() - start_time).total_seconds()
        
        return {
            "domain": domain,
            "query": query,
            "engines": engine_results,
            "total_results": len(merged_results),
            "merged_results": merged_results,
            "search_time": search_time
        }
    
    async def _search_site_serper(self, domain: str, query: str, count: int) -> List[Dict]:
        """Serper ile site araması"""
        site_query = f"site:{domain} {query} pdf" if query else f"site:{domain} pdf"
        results = await self.serper.search_pdfs(site_query, num=count)
        return results
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Cache istatistiklerini getir"""
        if self.cache:
            return self.cache.get_cache_stats()
        return {"message": "Cache disabled"}
    
    def clear_cache(self, engine: str = None) -> int:
        """Cache temizle"""
        if not self.cache:
            return 0
        
        if engine:
            return self.cache.clear_engine_cache(engine)
        return self.cache.clear_all_cache()
    
    def refresh_cache(self, engine: str = None) -> int:
        """Süresi dolmuş cache'i temizle"""
        if not self.cache:
            return 0
        return self.cache.clear_expired_cache()


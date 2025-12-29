"""
Multi-Engine Search Aggregator
Birden fazla arama motorundan sonuçları birleştir, duplicate kaldır
"""
import asyncio
from typing import List, Dict, Optional, Set
from urllib.parse import urlparse, unquote
import hashlib
import logging

from src.data.domains import is_premium_domain, is_excluded_domain
from src.search.query_builder import build_search_query

logger = logging.getLogger(__name__)


# Limitler
MAX_RESULTS_PER_ENGINE = 50   # Motor başına maksimum sonuç
MAX_TOTAL_RESULTS = 100       # Toplam maksimum sonuç


def normalize_url(url: str) -> str:
    """
    URL'yi normalize et - duplicate tespiti için
    
    - http/https farkını kaldır
    - www prefix'ini kaldır
    - Trailing slash'ı kaldır
    - URL decode
    - Lowercase
    """
    try:
        url = unquote(url).lower().strip()
        
        # Protokol kaldır
        url = url.replace("https://", "").replace("http://", "")
        
        # www kaldır
        if url.startswith("www."):
            url = url[4:]
        
        # Trailing slash kaldır
        url = url.rstrip("/")
        
        return url
    except Exception:
        return url


def url_hash(url: str) -> str:
    """URL'nin unique hash'ini oluştur"""
    normalized = normalize_url(url)
    return hashlib.md5(normalized.encode()).hexdigest()


class MultiEngineAggregator:
    """Çoklu arama motoru birleştirici"""
    
    def __init__(self):
        self.google_client = None
        self.brave_client = None
        self.yandex_client = None
        self._initialized = False
    
    async def _init_clients(self):
        """Lazy client initialization"""
        if self._initialized:
            return
        
        try:
            from src.search.google import GoogleSearchClient
            self.google_client = GoogleSearchClient()
        except Exception as e:
            logger.warning(f"Google client init failed: {e}")
        
        try:
            from src.search.brave import BraveSearchClient
            self.brave_client = BraveSearchClient()
        except Exception as e:
            logger.warning(f"Brave client init failed: {e}")
        
        try:
            from src.search.yandex import YandexSearchClient
            self.yandex_client = YandexSearchClient()
        except Exception as e:
            logger.warning(f"Yandex client init failed: {e}")
        
        self._initialized = True
    
    async def close(self):
        """Tüm client'ları kapat"""
        if self.google_client:
            await self.google_client.close()
        if self.brave_client:
            await self.brave_client.close()
        if self.yandex_client:
            await self.yandex_client.close()
    
    async def search_all_engines(
        self,
        query: str,
        engines: List[str] = None,
        language: str = "en",
        count_per_engine: int = MAX_RESULTS_PER_ENGINE
    ) -> Dict:
        """
        Tüm motorlarda paralel arama yap
        
        Args:
            query: Arama sorgusu (query_builder'dan)
            engines: Kullanılacak motorlar ["google", "brave", "yandex"]
            language: Dil kodu
            count_per_engine: Motor başına sonuç limiti
        
        Returns:
            {
                "results": [...],       # Tüm sonuçlar
                "engines": {...},       # Motor bazlı sonuçlar
                "stats": {...}          # İstatistikler
            }
        """
        await self._init_clients()
        
        if engines is None:
            engines = ["google", "brave", "yandex"]
        
        # Paralel arama görevleri
        tasks = []
        engine_names = []
        
        for engine in engines:
            if engine == "google" and self.google_client:
                tasks.append(self.google_client.search_pdfs(query, count_per_engine, language))
                engine_names.append("google")
            elif engine == "brave" and self.brave_client:
                tasks.append(self.brave_client.search_pdfs(query, count_per_engine, language))
                engine_names.append("brave")
            elif engine == "yandex" and self.yandex_client:
                tasks.append(self.yandex_client.search_pdfs(query, count_per_engine, language))
                engine_names.append("yandex")
        
        # Paralel çalıştır
        results_per_engine = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Sonuçları birleştir
        engine_results = {}
        all_results = []
        seen_urls: Set[str] = set()
        
        for engine_name, results in zip(engine_names, results_per_engine):
            if isinstance(results, Exception):
                logger.error(f"{engine_name} error: {results}")
                engine_results[engine_name] = {"count": 0, "error": str(results)}
                continue
            
            engine_results[engine_name] = {"count": len(results), "error": None}
            
            for result in results:
                url = result.get("url", "")
                url_key = url_hash(url)
                
                # Duplicate kontrolü
                if url_key in seen_urls:
                    continue
                seen_urls.add(url_key)
                
                # Hariç tutulan domain kontrolü
                if is_excluded_domain(url):
                    continue
                
                # Premium flag ekle
                result["is_premium"] = is_premium_domain(url)
                result["source"] = engine_name
                
                all_results.append(result)
        
        # Toplam limite uygula
        all_results = all_results[:MAX_TOTAL_RESULTS]
        
        return {
            "results": all_results,
            "engines": engine_results,
            "stats": {
                "total": len(all_results),
                "unique_domains": len(set(urlparse(r.get("url", "")).netloc for r in all_results)),
                "premium_count": sum(1 for r in all_results if r.get("is_premium")),
                "free_count": sum(1 for r in all_results if not r.get("is_premium"))
            }
        }
    
    async def search_with_query_builder(
        self,
        brand: Optional[str] = None,
        model: Optional[str] = None,
        category: str = "parts_catalog",
        engines: List[str] = None,
        language: str = "en"
    ) -> Dict:
        """
        Query builder ile arama yap
        
        Args:
            brand: Marka adı
            model: Model numarası
            category: Kategori kodu
            engines: Arama motorları
            language: Dil
        
        Returns:
            Birleştirilmiş sonuçlar
        """
        # OR operatörlü sorgu oluştur
        query = build_search_query(brand, model, category, engine="google")
        
        logger.info(f"Search query: {query}")
        
        return await self.search_all_engines(
            query=query,
            engines=engines,
            language=language
        )
    
    def separate_results(self, results: List[Dict]) -> Dict:
        """
        Sonuçları free/premium olarak ayır
        
        Args:
            results: Tüm sonuçlar
        
        Returns:
            {
                "all": [...],
                "free": [...],
                "premium": [...]
            }
        """
        free_results = [r for r in results if not r.get("is_premium")]
        premium_results = [r for r in results if r.get("is_premium")]
        
        return {
            "all": results,
            "free": free_results,
            "premium": premium_results
        }
    
    def paginate_results(
        self, 
        results: List[Dict], 
        page: int = 1, 
        per_page: int = 20
    ) -> Dict:
        """
        Sonuçları sayfala
        
        Args:
            results: Sonuç listesi
            page: Sayfa numarası (1'den başlar)
            per_page: Sayfa başına sonuç
        
        Returns:
            {
                "results": [...],
                "page": 1,
                "per_page": 20,
                "total": 100,
                "total_pages": 5
            }
        """
        total = len(results)
        total_pages = max(1, (total + per_page - 1) // per_page)
        
        # Sayfa sınırlarını kontrol et
        page = max(1, min(page, total_pages))
        
        start = (page - 1) * per_page
        end = start + per_page
        
        return {
            "results": results[start:end],
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages
        }


# Singleton instance
_aggregator_instance = None

def get_aggregator() -> MultiEngineAggregator:
    """Singleton aggregator instance döndür"""
    global _aggregator_instance
    if _aggregator_instance is None:
        _aggregator_instance = MultiEngineAggregator()
    return _aggregator_instance


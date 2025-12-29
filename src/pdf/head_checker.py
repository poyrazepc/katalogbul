"""
PDF HEAD Request ile Boyut ve Metadata Kontrolü

HEAD request ile dosya boyutunu ve content-type'ı öğren.
Dosyayı indirmeden hızlıca bilgi al.
"""
import asyncio
import aiohttp
from typing import List, Dict, Optional, NamedTuple
from dataclasses import dataclass
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class PDFInfo:
    """PDF dosya bilgileri"""
    url: str
    size_bytes: Optional[int] = None
    size_mb: Optional[float] = None
    content_type: Optional[str] = None
    is_valid_pdf: bool = False
    error: Optional[str] = None
    
    @property
    def size_formatted(self) -> str:
        """Boyutu okunabilir formatta döndür"""
        if self.size_bytes is None:
            return "Bilinmiyor"
        
        if self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        elif self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        else:
            return f"{self.size_bytes / (1024 * 1024):.1f} MB"


async def get_pdf_info(
    url: str,
    session: aiohttp.ClientSession = None,
    timeout: int = 10
) -> PDFInfo:
    """
    Tek PDF için HEAD request ile bilgi al
    
    Args:
        url: PDF URL'si
        session: Mevcut aiohttp session (opsiyonel)
        timeout: İstek timeout süresi (saniye)
    
    Returns:
        PDFInfo objesi
    """
    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        async with session.head(
            url, 
            timeout=aiohttp.ClientTimeout(total=timeout),
            headers=headers,
            allow_redirects=True
        ) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            content_length = response.headers.get("Content-Length")
            
            size_bytes = int(content_length) if content_length else None
            size_mb = size_bytes / (1024 * 1024) if size_bytes else None
            
            is_valid = (
                response.status == 200 and
                ("pdf" in content_type or url.lower().endswith(".pdf"))
            )
            
            return PDFInfo(
                url=url,
                size_bytes=size_bytes,
                size_mb=size_mb,
                content_type=content_type,
                is_valid_pdf=is_valid,
                error=None
            )
    
    except asyncio.TimeoutError:
        return PDFInfo(url=url, error="Timeout")
    except aiohttp.ClientError as e:
        return PDFInfo(url=url, error=f"Connection error: {str(e)[:50]}")
    except Exception as e:
        return PDFInfo(url=url, error=str(e)[:50])
    finally:
        if close_session:
            await session.close()


async def get_bulk_pdf_info(
    urls: List[str],
    max_concurrent: int = 50,
    timeout: int = 10
) -> Dict[str, PDFInfo]:
    """
    Birden fazla PDF için paralel HEAD request
    
    Args:
        urls: PDF URL listesi
        max_concurrent: Eşzamanlı istek limiti
        timeout: İstek timeout süresi
    
    Returns:
        {url: PDFInfo} dictionary
    """
    results = {}
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def fetch_with_semaphore(url: str, session: aiohttp.ClientSession) -> tuple:
        async with semaphore:
            info = await get_pdf_info(url, session, timeout)
            return url, info
    
    connector = aiohttp.TCPConnector(limit=max_concurrent, limit_per_host=5)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_with_semaphore(url, session) for url in urls]
        
        for coro in asyncio.as_completed(tasks):
            try:
                url, info = await coro
                results[url] = info
            except Exception as e:
                logger.error(f"Bulk PDF info error: {e}")
    
    return results


async def enrich_results_with_size(
    results: List[Dict],
    max_concurrent: int = 10
) -> List[Dict]:
    """
    Arama sonuçlarına boyut bilgisi ekle
    
    Args:
        results: Arama sonuçları listesi
        max_concurrent: Eşzamanlı istek limiti
    
    Returns:
        Boyut bilgisi eklenmiş sonuçlar
    """
    urls = [r.get("url", "") for r in results if r.get("url")]
    
    pdf_infos = await get_bulk_pdf_info(urls, max_concurrent)
    
    for result in results:
        url = result.get("url", "")
        if url in pdf_infos:
            info = pdf_infos[url]
            result["size_bytes"] = info.size_bytes
            result["size_mb"] = info.size_mb
            result["size_formatted"] = info.size_formatted
            result["is_valid_pdf"] = info.is_valid_pdf
    
    return results


# Test
if __name__ == "__main__":
    import asyncio
    
    async def test():
        # Örnek PDF URL'leri
        test_urls = [
            "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
            "https://example.com/nonexistent.pdf"
        ]
        
        print("Testing single URL...")
        info = await get_pdf_info(test_urls[0])
        print(f"  URL: {info.url}")
        print(f"  Size: {info.size_formatted}")
        print(f"  Valid: {info.is_valid_pdf}")
        
        print("\nTesting bulk URLs...")
        results = await get_bulk_pdf_info(test_urls)
        for url, info in results.items():
            print(f"  {url[:50]}... -> {info.size_formatted}")
    
    asyncio.run(test())


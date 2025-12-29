"""
PDF Analyzer - Range Request ile Hızlı Metadata Okuma
PDF dosyasının tamamını indirmeden sayfa sayısı tespiti
"""
import re
import asyncio
import aiohttp
from typing import Optional, Dict, List


async def get_pdf_page_count_fast(url: str, timeout: int = 15) -> Optional[int]:
    """
    PDF'in tamamını indirmeden sayfa sayısını bul
    HTTP Range header kullanarak sadece gerekli kısımları oku
    
    Args:
        url: PDF URL'i
        timeout: Timeout süresi (saniye)
        
    Returns:
        Sayfa sayısı veya None
    """
    try:
        async with aiohttp.ClientSession() as session:
            # 1. Önce dosya boyutunu al (HEAD request)
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    return None
                
                content_length = resp.headers.get("Content-Length")
                if not content_length:
                    return None
                
                file_size = int(content_length)
                
                # Çok küçük dosyalar için direkt oku
                if file_size < 10000:
                    return await _read_full_pdf_count(session, url, timeout)
            
            # 2. Son 5KB'ı oku (Cross-Reference Table burada)
            # PDF dosyalarında sayfa sayısı bilgisi genellikle sonda bulunur
            start_byte = max(0, file_size - 5120)
            headers = {"Range": f"bytes={start_byte}-{file_size - 1}"}
            
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status not in (200, 206):
                    return None
                
                content = await resp.read()
                
                # /Count değerini ara
                # PDF'de sayfa sayısı: /Count 245 veya /Count245
                matches = re.findall(rb'/Count\s*(\d+)', content)
                
                if matches:
                    # En büyük değer genelde toplam sayfa
                    counts = [int(m) for m in matches]
                    return max(counts)
                
                # Bulunamadıysa baştan da dene
                return await _read_pdf_header_count(session, url, timeout)
                
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        print(f"PDF analyze error for {url}: {e}")
        return None


async def _read_pdf_header_count(
    session: aiohttp.ClientSession,
    url: str,
    timeout: int
) -> Optional[int]:
    """PDF başlığından sayfa sayısı oku"""
    try:
        headers = {"Range": "bytes=0-10240"}  # İlk 10KB
        
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status not in (200, 206):
                return None
            
            content = await resp.read()
            
            # /Count değerini ara
            matches = re.findall(rb'/Count\s*(\d+)', content)
            
            if matches:
                counts = [int(m) for m in matches]
                return max(counts)
            
            return None
    except:
        return None


async def _read_full_pdf_count(
    session: aiohttp.ClientSession,
    url: str,
    timeout: int
) -> Optional[int]:
    """Küçük PDF'leri tamamen oku"""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status != 200:
                return None
            
            content = await resp.read()
            
            matches = re.findall(rb'/Count\s*(\d+)', content)
            
            if matches:
                counts = [int(m) for m in matches]
                return max(counts)
            
            return None
    except:
        return None


async def get_pdf_file_size(url: str, timeout: int = 10) -> Optional[int]:
    """
    PDF dosya boyutunu al (HEAD request)
    
    Returns:
        Dosya boyutu (bytes) veya None
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    return None
                
                content_length = resp.headers.get("Content-Length")
                if content_length:
                    return int(content_length)
                
                return None
    except:
        return None


async def analyze_pdf(url: str) -> Dict[str, Optional[int]]:
    """
    PDF analiz et - hem boyut hem sayfa sayısı
    
    Returns:
        {"page_count": int|None, "file_size": int|None}
    """
    try:
        async with aiohttp.ClientSession() as session:
            # HEAD request ile boyut al
            file_size = None
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    content_length = resp.headers.get("Content-Length")
                    if content_length:
                        file_size = int(content_length)
            
            # Sayfa sayısı
            page_count = await get_pdf_page_count_fast(url)
            
            return {
                "page_count": page_count,
                "file_size": file_size
            }
    except:
        return {"page_count": None, "file_size": None}


async def analyze_pdf_batch(urls: List[str], concurrency: int = 5) -> Dict[str, Dict]:
    """
    Birden fazla PDF'i paralel analiz et
    
    Args:
        urls: PDF URL listesi
        concurrency: Eşzamanlı istek sayısı
        
    Returns:
        {url: {"page_count": int, "file_size": int}, ...}
    """
    semaphore = asyncio.Semaphore(concurrency)
    
    async def analyze_with_limit(url: str) -> tuple:
        async with semaphore:
            result = await analyze_pdf(url)
            return url, result
    
    tasks = [analyze_with_limit(url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    output = {}
    for result in results:
        if isinstance(result, tuple):
            url, data = result
            output[url] = data
        elif isinstance(result, Exception):
            print(f"Batch analyze error: {result}")
    
    return output


def update_cache_with_metadata(db_path: str, url: str, page_count: int, file_size: int):
    """
    Cache'deki sonuca metadata ekle
    
    Args:
        db_path: Veritabanı yolu
        url: PDF URL'i
        page_count: Sayfa sayısı
        file_size: Dosya boyutu
    """
    import sqlite3
    import json
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # search_cache tablosundaki results JSON'larını güncelle
        cursor.execute("SELECT id, results FROM search_cache")
        
        for row in cursor.fetchall():
            cache_id = row[0]
            results_json = row[1]
            
            if not results_json:
                continue
            
            try:
                results = json.loads(results_json)
                modified = False
                
                for result in results:
                    if result.get("url") == url:
                        if page_count is not None:
                            result["page_count"] = page_count
                            modified = True
                        if file_size is not None:
                            result["file_size_bytes"] = file_size
                            modified = True
                
                if modified:
                    cursor.execute("""
                        UPDATE search_cache SET results = ? WHERE id = ?
                    """, (json.dumps(results, ensure_ascii=False), cache_id))
                    
            except json.JSONDecodeError:
                continue
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Cache update error: {e}")


"""
Directory Listing Scraper

Açık dizin listelerinden PDF bağlantılarını çıkar.
Apache/Nginx directory listing formatlarını destekler.
"""
import aiohttp
import asyncio
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse, unquote
import re
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# Directory listing belirteci pattern'leri
DIRECTORY_PATTERNS = [
    r'Index of',
    r'Directory listing',
    r'Parent Directory',
    r'\[DIR\]',
    r'\[PARENTDIR\]',
    r'<pre>',  # Apache style
]


def is_directory_listing(html: str) -> bool:
    """HTML'in directory listing olup olmadığını kontrol et"""
    return any(re.search(pattern, html, re.IGNORECASE) for pattern in DIRECTORY_PATTERNS)


def extract_pdf_links(html: str, base_url: str) -> List[str]:
    """
    HTML'den PDF bağlantılarını çıkar
    
    Args:
        html: Sayfa HTML içeriği
        base_url: Temel URL (relative link'ler için)
    
    Returns:
        Absolute PDF URL listesi
    """
    pdf_links = []
    seen: Set[str] = set()
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Tüm <a> tag'lerini bul
        for link in soup.find_all('a', href=True):
            href = link['href']
            
            # PDF kontrolü
            if not href.lower().endswith('.pdf'):
                continue
            
            # Absolute URL oluştur
            absolute_url = urljoin(base_url, href)
            
            # Normalize ve duplicate kontrolü
            normalized = unquote(absolute_url).lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            
            pdf_links.append(absolute_url)
    
    except Exception as e:
        logger.error(f"PDF link extraction error: {e}")
    
    return pdf_links


async def scrape_directory(
    url: str,
    follow_subdirs: bool = True,
    max_depth: int = 2,
    max_pdfs: int = 100,
    timeout: int = 15
) -> List[str]:
    """
    Dizin listesini tara ve PDF bağlantılarını topla
    
    Args:
        url: Dizin URL'si
        follow_subdirs: Alt dizinlere de git
        max_depth: Maksimum derinlik
        max_pdfs: Maksimum PDF sayısı
        timeout: İstek timeout süresi
    
    Returns:
        PDF URL listesi
    """
    all_pdfs: List[str] = []
    visited: Set[str] = set()
    
    async def crawl(current_url: str, depth: int):
        if depth > max_depth or len(all_pdfs) >= max_pdfs:
            return
        
        if current_url in visited:
            return
        visited.add(current_url)
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                
                async with session.get(
                    current_url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    headers=headers
                ) as response:
                    if response.status != 200:
                        return
                    
                    html = await response.text()
                    
                    # Directory listing kontrolü
                    if not is_directory_listing(html):
                        return
                    
                    # PDF'leri çıkar
                    pdfs = extract_pdf_links(html, current_url)
                    for pdf in pdfs:
                        if len(all_pdfs) >= max_pdfs:
                            break
                        all_pdfs.append(pdf)
                    
                    # Alt dizinleri bul ve takip et
                    if follow_subdirs:
                        soup = BeautifulSoup(html, 'html.parser')
                        for link in soup.find_all('a', href=True):
                            href = link['href']
                            
                            # Üst dizin linklerini atla
                            if href in ['../', '../', '/', '.']:
                                continue
                            
                            # Dizin linki mi? (/ ile bitiyor)
                            if href.endswith('/'):
                                subdir_url = urljoin(current_url, href)
                                await crawl(subdir_url, depth + 1)
        
        except asyncio.TimeoutError:
            logger.warning(f"Timeout: {current_url}")
        except Exception as e:
            logger.error(f"Scrape error for {current_url}: {e}")
    
    await crawl(url, 0)
    
    return all_pdfs[:max_pdfs]


async def find_related_pdfs(pdf_url: str, max_pdfs: int = 20) -> List[str]:
    """
    Bir PDF URL'sinden yola çıkarak aynı dizindeki diğer PDF'leri bul
    
    Args:
        pdf_url: Mevcut PDF URL'si
        max_pdfs: Maksimum PDF sayısı
    
    Returns:
        İlgili PDF URL listesi
    """
    try:
        parsed = urlparse(pdf_url)
        path_parts = parsed.path.rsplit('/', 1)
        
        if len(path_parts) > 1:
            directory_path = path_parts[0] + '/'
            directory_url = f"{parsed.scheme}://{parsed.netloc}{directory_path}"
            
            return await scrape_directory(
                directory_url,
                follow_subdirs=False,
                max_depth=0,
                max_pdfs=max_pdfs
            )
    except Exception as e:
        logger.error(f"Find related PDFs error: {e}")
    
    return []


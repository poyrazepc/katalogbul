"""
Utility Functions
"""
import logging
import aiohttp
from typing import Optional, Dict
from src.data.brands import BRAND_LIST, get_brand_aliases
from src.data.categories import CATEGORY_MAPPING, CATEGORY_LABELS


def setup_logging():
    """Merkezi loglama yapılandırması"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("app.log"),
            logging.StreamHandler()
        ]
    )


async def get_pdf_size(url: str, session: aiohttp.ClientSession = None) -> Optional[int]:
    """Tek PDF'in boyutunu HEAD request ile al"""
    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True
    
    try:
        async with session.head(url, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=True) as response:
            content_length = response.headers.get("Content-Length")
            if content_length:
                return int(content_length)
            return None
    except Exception:
        return None
    finally:
        if close_session:
            await session.close()


async def get_multiple_pdf_sizes(urls: list) -> Dict[str, Optional[int]]:
    """Birden fazla PDF'in boyutunu paralel olarak al"""
    import asyncio
    
    async with aiohttp.ClientSession() as session:
        tasks = [get_pdf_size(url, session) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            url: (size if isinstance(size, int) else None) 
            for url, size in zip(urls, results)
        }


def extract_brand_from_query(query: str) -> Optional[str]:
    """
    Query string'den marka çıkar
    
    Args:
        query: Arama sorgusu (örn: "caterpillar 320D", "volvo EC210")
    
    Returns:
        Marka adı veya None
    """
    if not query:
        return None
    
    query_lower = query.lower().strip()
    
    # BRAND_LIST'teki markaları kontrol et
    for brand in BRAND_LIST:
        brand_lower = brand.lower()
        
        # Tam eşleşme veya başta geçiyorsa
        if query_lower.startswith(brand_lower) or f" {brand_lower} " in f" {query_lower} ":
            return brand
        
        # Alias kontrolü
        aliases = get_brand_aliases(brand)
        for alias in aliases:
            alias_lower = alias.lower()
            if query_lower.startswith(alias_lower) or f" {alias_lower} " in f" {query_lower} ":
                return brand
    
    return None


def map_doc_type_to_category(doc_type: Optional[str]) -> str:
    """
    Eski doc_type'ı yeni category'ye çevir
    
    Args:
        doc_type: Eski doc_type (parts, service, electrical, vb.)
    
    Returns:
        Yeni category kodu
    """
    if not doc_type:
        return "parts_catalog"
    
    # Mapping tablosu
    mapping = {
        "parts": "parts_catalog",
        "service": "service_manual",
        "electrical": "electrical_diagram",
        "hydraulic": "hydraulic_diagram",
        "troubleshooting": "troubleshooting",
        # Yeni kategori kodları zaten doğruysa olduğu gibi döndür
        "parts_catalog": "parts_catalog",
        "service_manual": "service_manual",
        "electrical_diagram": "electrical_diagram",
        "hydraulic_diagram": "hydraulic_diagram",
    }
    
    return mapping.get(doc_type.lower(), "parts_catalog")


def get_category_label(category: str) -> str:
    """Kategori kodundan Türkçe label al"""
    return CATEGORY_LABELS.get(category, category.replace("_", " ").title())

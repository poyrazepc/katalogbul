"""
Site Search Query Builder

Mevcut PDF'den yola çıkarak aynı sitede daha fazla içerik bul.
"""
from typing import List, Dict, Optional
from urllib.parse import urlparse, unquote
import logging

logger = logging.getLogger(__name__)


def build_site_search_query(
    domain: str,
    path_hint: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    filetype: str = "pdf"
) -> str:
    """
    Site içi arama sorgusu oluştur
    
    Args:
        domain: Site domain (örn: "parts.cat.com")
        path_hint: Path ipucu (örn: "/manuals/")
        keywords: Ek arama kelimeleri
        filetype: Dosya tipi
    
    Returns:
        Google/Serper için arama sorgusu
    
    Example:
        >>> build_site_search_query("parts.cat.com", "/manuals/", ["320D"])
        'site:parts.cat.com inurl:"/manuals/" "320D" filetype:pdf'
    """
    parts = [f"site:{domain}"]
    
    if path_hint:
        # Path'i temizle
        path_hint = path_hint.strip("/")
        parts.append(f'inurl:"{path_hint}"')
    
    if keywords:
        for kw in keywords:
            parts.append(f'"{kw}"')
    
    parts.append(f"filetype:{filetype}")
    
    return " ".join(parts)


def extract_domain_and_path(url: str) -> Dict[str, str]:
    """
    URL'den domain ve path bilgilerini çıkar
    
    Args:
        url: Tam URL
    
    Returns:
        {"domain": "...", "path": "...", "directory": "..."}
    """
    try:
        parsed = urlparse(url)
        
        # Dizin path'ini çıkar (dosya adı hariç)
        path_parts = parsed.path.rsplit('/', 1)
        directory = path_parts[0] if len(path_parts) > 1 else ""
        
        return {
            "domain": parsed.netloc,
            "path": parsed.path,
            "directory": directory,
            "scheme": parsed.scheme
        }
    except Exception:
        return {"domain": "", "path": "", "directory": "", "scheme": "https"}


def discover_from_pdf_url(pdf_url: str) -> List[str]:
    """
    Bir PDF URL'sinden keşif sorguları oluştur
    
    Args:
        pdf_url: Mevcut PDF URL'si
    
    Returns:
        Arama sorguları listesi
    
    Example:
        >>> discover_from_pdf_url("https://parts.cat.com/manuals/320D/parts.pdf")
        [
            'site:parts.cat.com filetype:pdf',
            'site:parts.cat.com inurl:"manuals" filetype:pdf',
            'site:parts.cat.com inurl:"manuals/320D" filetype:pdf'
        ]
    """
    info = extract_domain_and_path(pdf_url)
    queries = []
    
    if not info["domain"]:
        return queries
    
    # 1. Sadece domain araması
    queries.append(f'site:{info["domain"]} filetype:pdf')
    
    # 2. Dizin bazlı arama (her seviye için)
    if info["directory"]:
        path_parts = info["directory"].strip("/").split("/")
        
        # İlk seviye
        if path_parts[0]:
            queries.append(f'site:{info["domain"]} inurl:"{path_parts[0]}" filetype:pdf')
        
        # Tam path (max 3 seviye)
        if len(path_parts) > 1:
            full_path = "/".join(path_parts[:3])
            queries.append(f'site:{info["domain"]} inurl:"{full_path}" filetype:pdf')
    
    return queries


def build_brand_site_query(
    domain: str,
    brand: str,
    model: Optional[str] = None,
    category: str = "parts"
) -> str:
    """
    Marka/model bazlı site araması
    
    Args:
        domain: Site domain
        brand: Marka adı
        model: Model numarası
        category: Kategori (parts, service, vb.)
    
    Returns:
        Arama sorgusu
    """
    from src.data.categories import get_category_terms
    
    parts = [f"site:{domain}"]
    
    parts.append(f'"{brand}"')
    
    if model:
        parts.append(f'"{model}"')
    
    # Kategori terimlerinden birini ekle
    terms = get_category_terms(category, max_terms=1)
    if terms:
        parts.append(f'"{terms[0]}"')
    
    parts.append("filetype:pdf")
    
    return " ".join(parts)


async def discover_more_from_source(
    source_url: str,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    use_google: bool = True,
    use_brave: bool = True
) -> List[Dict]:
    """
    Mevcut kaynaktan daha fazla PDF keşfet
    
    Args:
        source_url: Kaynak PDF URL'si
        brand: Marka filtresi
        model: Model filtresi
        use_google: Google araması kullan
        use_brave: Brave araması kullan
    
    Returns:
        Keşfedilen PDF listesi
    """
    from src.search.aggregator import get_aggregator
    
    queries = discover_from_pdf_url(source_url)
    
    if not queries:
        return []
    
    aggregator = get_aggregator()
    all_results = []
    
    engines = []
    if use_google:
        engines.append("google")
    if use_brave:
        engines.append("brave")
    
    for query in queries[:2]:  # İlk 2 sorguyu kullan
        try:
            result = await aggregator.search_all_engines(
                query=query,
                engines=engines,
                count_per_engine=20
            )
            all_results.extend(result.get("results", []))
        except Exception as e:
            logger.error(f"Discovery error: {e}")
    
    # Duplicate kaldır
    seen = set()
    unique = []
    for r in all_results:
        url = r.get("url", "")
        if url not in seen:
            seen.add(url)
            unique.append(r)
    
    return unique


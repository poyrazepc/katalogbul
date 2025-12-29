"""
Arama Sorgusu Oluşturucu

Strateji:
- Kullanıcının yazdığı (marka/model) → Zorunlu, çift tırnak içinde
- Kategori core keyword → Zorunlu, çift tırnak içinde  
- Kategori varyasyonları → Opsiyonel, varsa gelsin

Örnek (parts_catalog):
  "hitachi" "parts" catalog catalogue manual book breakdown filetype:pdf
  
  Zorunlu: "hitachi" ve "parts" mutlaka geçmeli
  Opsiyonel: catalog, catalogue, manual, book... bunlardan biri varsa gelsin
"""
from typing import List, Optional, Set
from src.data.categories import SEARCH_TERMS


# Kategori için ZORUNLU anahtar kelime (çift tırnak içinde olacak)
CATEGORY_CORE_KEYWORDS = {
    "parts_catalog": "parts",
    "service_manual": "service", 
    "electrical_diagram": "wiring",
    "hydraulic_diagram": "hydraulic",
    "troubleshooting": "fault"
}


def _extract_variant_words(category: str) -> str:
    """
    Kategori varyasyonlarından benzersiz kelimeleri çıkar
    
    "parts catalog", "parts manual", "parts book" → "catalog manual book"
    (parts zaten core keyword olarak eklenecek)
    
    Tırnak içinde olmayan kelimeler opsiyonel - varsa gelir, yoksa da sonuç döner
    """
    terms = SEARCH_TERMS.get(category, SEARCH_TERMS["parts_catalog"])
    core = CATEGORY_CORE_KEYWORDS.get(category, "parts")
    
    # Tüm varyasyonlardan kelimeleri topla
    words: Set[str] = set()
    for term in terms:
        for word in term.lower().split():
            # Core keyword'ü ve çok genel kelimeleri atla
            if word != core and word not in ["the", "and", "of", "for"]:
                words.add(word)
    
    return " ".join(sorted(words))


def build_search_query(
    brand: Optional[str] = None,
    model: Optional[str] = None,
    category: str = "parts_catalog",
    filetype: str = "pdf",
    max_terms: int = 4,  # Geriye uyumluluk için
    engine: str = "google"
) -> str:
    """
    Arama sorgusu oluştur
    
    Args:
        brand: Marka adı (opsiyonel)
        model: Model/parça numarası veya kullanıcının yazdığı metin
        category: Kategori kodu
        filetype: Dosya tipi
        engine: Arama motoru
    
    Returns:
        Arama sorgusu
    
    Examples:
        >>> build_search_query("hitachi", None, "parts_catalog")
        '"hitachi" "parts" catalog catalogue manual book breakdown diagram exploded illustrated spare filetype:pdf'
        
        >>> build_search_query(None, "ZX200", "parts_catalog")  
        '"ZX200" "parts" catalog catalogue manual book breakdown diagram exploded illustrated spare filetype:pdf'
        
        >>> build_search_query("volvo", "EC210", "service_manual")
        '"volvo" "EC210" "service" factory maintenance manual overhaul repair shop technical workshop filetype:pdf'
    """
    parts = []
    
    # 1. Marka veya kullanıcı metni (ZORUNLU - çift tırnak)
    if brand:
        parts.append(f'"{brand.lower()}"')
    
    # 2. Model/parça numarası (ZORUNLU - çift tırnak)
    if model:
        parts.append(f'"{model.strip()}"')
    
    # 3. Kategori core keyword (ZORUNLU - çift tırnak)
    core_keyword = CATEGORY_CORE_KEYWORDS.get(category, "parts")
    parts.append(f'"{core_keyword}"')
    
    # 4. Kategori varyasyon kelimeleri (OPSİYONEL - tırnak yok)
    variant_words = _extract_variant_words(category)
    if variant_words:
        parts.append(variant_words)
    
    # 5. Dosya tipi filtresi
    if filetype:
        if engine.lower() == "yandex":
            parts.append(f"mime:{filetype}")
        else:
            parts.append(f"filetype:{filetype}")
    
    return " ".join(parts)


# Geriye uyumluluk için eski fonksiyonlar
def build_or_clause(terms: List[str], quote: bool = True) -> str:
    """Artık kullanılmıyor - geriye uyumluluk için bırakıldı"""
    if not terms:
        return ""
    if len(terms) == 1:
        term = terms[0]
        return f'"{term}"' if quote and " " in term else term
    if quote:
        formatted = [f'"{t}"' if " " in t else t for t in terms]
    else:
        formatted = terms
    return f"({' OR '.join(formatted)})"


def build_site_search_query(
    domain: str,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    category: str = "parts_catalog"
) -> str:
    """
    Belirli bir site içinde arama sorgusu oluştur
    
    Args:
        domain: Site domain (örn: "parts.cat.com")
        brand: Marka adı
        model: Model numarası
        category: Kategori
    
    Returns:
        site:domain formatında sorgu
    """
    query = build_search_query(brand, model, category)
    return f"site:{domain} {query}"


def build_discover_query(pdf_url: str) -> str:
    """
    Mevcut PDF'den yola çıkarak benzer içerik keşfet sorgusu
    
    Args:
        pdf_url: Bulunan PDF URL'si
    
    Returns:
        site:domain inurl:path formatında sorgu
    """
    from urllib.parse import urlparse
    
    try:
        parsed = urlparse(pdf_url)
        domain = parsed.netloc
        
        # Path'ten dizin çıkar
        path_parts = parsed.path.rsplit('/', 1)
        if len(path_parts) > 1:
            directory = path_parts[0]
            return f'site:{domain} inurl:"{directory}" filetype:pdf'
        
        return f"site:{domain} filetype:pdf"
    except Exception:
        return ""


# Test
if __name__ == "__main__":
    # Test örnekleri
    print("=== Query Builder Test ===\n")
    
    q1 = build_search_query("caterpillar", "320D", "parts_catalog")
    print(f"1. CAT 320D Parts: {q1}\n")
    
    q2 = build_search_query("volvo", "EC210", "service_manual")
    print(f"2. Volvo EC210 Service: {q2}\n")
    
    q3 = build_search_query("komatsu", "PC200-8", "hydraulic_diagram")
    print(f"3. Komatsu PC200-8 Hydraulic: {q3}\n")
    
    q4 = build_search_query("caterpillar", "320D", "parts_catalog", engine="yandex")
    print(f"4. CAT 320D (Yandex): {q4}\n")
    
    q5 = build_site_search_query("parts.cat.com", "caterpillar", "320D")
    print(f"5. Site Search: {q5}\n")


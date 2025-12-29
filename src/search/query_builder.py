"""
Arama Sorgusu Oluşturucu - Çok Dilli Destek (TR, EN, RU, ZH)

Strateji:
- Kullanıcının yazdığı (marka/model) → Zorunlu, çift tırnak içinde
- Kategori core keyword → Zorunlu, çift tırnak içinde  
- Kategori varyasyonları → Opsiyonel, varsa gelsin

Örnek (parts_catalog, en):
  "hitachi" "parts" catalog catalogue manual book breakdown filetype:pdf
  
Örnek (parts_catalog, tr):
  "hitachi" "parça" kataloğu kitabı eksplozyon filetype:pdf
"""
from typing import List, Optional, Set, Dict
from src.data.categories import SEARCH_TERMS_BY_LANG, SEARCH_TERMS


# Dil bazlı kategori core keyword'leri
CATEGORY_CORE_KEYWORDS_BY_LANG: Dict[str, Dict[str, str]] = {
    "en": {
        "parts_catalog": "parts",
        "service_manual": "service", 
        "electrical_diagram": "wiring",
        "hydraulic_diagram": "hydraulic",
        "troubleshooting": "fault"
    },
    "tr": {
        "parts_catalog": "parça",
        "service_manual": "servis", 
        "electrical_diagram": "elektrik",
        "hydraulic_diagram": "hidrolik",
        "troubleshooting": "arıza"
    },
    "ru": {
        "parts_catalog": "запчастей",
        "service_manual": "ремонту", 
        "electrical_diagram": "электрическая",
        "hydraulic_diagram": "гидравлическая",
        "troubleshooting": "ошибок"
    },
    "zh": {
        "parts_catalog": "零件",
        "service_manual": "维修", 
        "electrical_diagram": "电气",
        "hydraulic_diagram": "液压",
        "troubleshooting": "故障"
    }
}

# Geriye uyumluluk - varsayılan İngilizce
CATEGORY_CORE_KEYWORDS = CATEGORY_CORE_KEYWORDS_BY_LANG["en"]


def _extract_variant_words(category: str, language: str = "en") -> str:
    """
    Kategori varyasyonlarından benzersiz kelimeleri çıkar
    
    "parts catalog", "parts manual", "parts book" → "catalog manual book"
    (parts zaten core keyword olarak eklenecek)
    
    Tırnak içinde olmayan kelimeler opsiyonel - varsa gelir, yoksa da sonuç döner
    """
    # Dil için terimleri al
    lang_terms = SEARCH_TERMS_BY_LANG.get(language, SEARCH_TERMS_BY_LANG.get("en", {}))
    terms = lang_terms.get(category, lang_terms.get("parts_catalog", []))
    
    # Core keyword'ü al
    lang_core = CATEGORY_CORE_KEYWORDS_BY_LANG.get(language, CATEGORY_CORE_KEYWORDS_BY_LANG["en"])
    core = lang_core.get(category, "parts")
    
    # Tüm varyasyonlardan kelimeleri topla
    words: Set[str] = set()
    for term in terms:
        for word in term.lower().split():
            # Core keyword'ü ve çok genel kelimeleri atla
            if word != core.lower() and word not in ["the", "and", "of", "for", "по", "по", "и"]:
                words.add(word)
    
    return " ".join(sorted(words))


def build_search_query(
    brand: Optional[str] = None,
    model: Optional[str] = None,
    category: str = "parts_catalog",
    filetype: str = "pdf",
    max_terms: int = 4,  # Geriye uyumluluk için
    engine: str = "google",
    language: str = "en"
) -> str:
    """
    Arama sorgusu oluştur - Dil desteği ile
    
    Args:
        brand: Marka adı (opsiyonel)
        model: Model/parça numarası veya kullanıcının yazdığı metin
        category: Kategori kodu
        filetype: Dosya tipi
        engine: Arama motoru
        language: Dil kodu (en, tr, ru, zh)
    
    Returns:
        Arama sorgusu
    
    Examples:
        >>> build_search_query("hitachi", None, "parts_catalog", language="en")
        '"hitachi" "parts" catalog catalogue manual book breakdown filetype:pdf'
        
        >>> build_search_query("hitachi", None, "parts_catalog", language="tr")
        '"hitachi" "parça" kataloğu kitabı eksplozyon filetype:pdf'
        
        >>> build_search_query("volvo", "EC210", "service_manual", language="ru")
        '"volvo" "EC210" "ремонту" руководство обслуживанию сервисное filetype:pdf'
    """
    parts = []
    
    # 1. Marka veya kullanıcı metni (ZORUNLU - çift tırnak)
    if brand:
        parts.append(f'"{brand.lower()}"')
    
    # 2. Model/parça numarası (ZORUNLU - çift tırnak)
    if model:
        parts.append(f'"{model.strip()}"')
    
    # 3. Kategori core keyword (ZORUNLU - çift tırnak) - Dile göre
    lang_core = CATEGORY_CORE_KEYWORDS_BY_LANG.get(language, CATEGORY_CORE_KEYWORDS_BY_LANG["en"])
    core_keyword = lang_core.get(category, "parts")
    parts.append(f'"{core_keyword}"')
    
    # 4. Kategori varyasyon kelimeleri (OPSİYONEL - tırnak yok) - Dile göre
    variant_words = _extract_variant_words(category, language)
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
    category: str = "parts_catalog",
    language: str = "en"
) -> str:
    """
    Belirli bir site içinde arama sorgusu oluştur
    
    Args:
        domain: Site domain (örn: "parts.cat.com")
        brand: Marka adı
        model: Model numarası
        category: Kategori
        language: Dil kodu
    
    Returns:
        site:domain formatında sorgu
    """
    query = build_search_query(brand, model, category, language=language)
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
    print("=== Query Builder Test - Çok Dilli ===\n")
    
    # İngilizce
    q1 = build_search_query("caterpillar", "320D", "parts_catalog", language="en")
    print(f"1. CAT 320D Parts (EN): {q1}\n")
    
    # Türkçe
    q2 = build_search_query("caterpillar", "320D", "parts_catalog", language="tr")
    print(f"2. CAT 320D Parça (TR): {q2}\n")
    
    # Rusça
    q3 = build_search_query("komatsu", "PC200-8", "service_manual", language="ru")
    print(f"3. Komatsu PC200-8 Servis (RU): {q3}\n")
    
    # Çince
    q4 = build_search_query("volvo", "EC210", "parts_catalog", language="zh")
    print(f"4. Volvo EC210 Parts (ZH): {q4}\n")
    
    # Yandex motor desteği
    q5 = build_search_query("hitachi", "ZX200", "hydraulic_diagram", engine="yandex", language="en")
    print(f"5. Hitachi ZX200 Hydraulic (Yandex): {q5}\n")

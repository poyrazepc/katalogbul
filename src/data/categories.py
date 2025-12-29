"""
Kategori ve Arama Terimleri
"""
from typing import List, Dict

# Kategori bazlı arama terimleri
SEARCH_TERMS: Dict[str, List[str]] = {
    "parts_catalog": [
        "parts catalog",
        "parts catalogue",
        "illustrated parts catalog",
        "parts manual",
        "spare parts catalog",
        "parts book",
        "parts breakdown",
        "exploded parts diagram"
    ],
    
    "service_manual": [
        "service manual",
        "workshop manual",
        "repair manual",
        "shop manual",
        "overhaul manual",
        "maintenance manual",
        "technical manual",
        "factory service manual"
    ],
    
    "electrical_diagram": [
        "wiring diagram",
        "electrical schematic",
        "wire harness diagram",
        "circuit diagram",
        "electrical diagram",
        "electrical wiring diagram"
    ],
    
    "hydraulic_diagram": [
        "hydraulic schematic",
        "hydraulic diagram",
        "hydraulic circuit diagram",
        "hydraulic system diagram",
        "hydraulic flow diagram"
    ],
    
    "troubleshooting": [
        "troubleshooting guide",
        "troubleshooting manual",
        "fault code list",
        "error code list",
        "diagnostic manual",
        "fault finding guide",
        "DTC codes"
    ]
}

# Türkçe kategori isimleri (Frontend için)
CATEGORY_LABELS: Dict[str, str] = {
    "parts_catalog": "Yedek Parça Kataloğu",
    "service_manual": "Servis / Tamir Kılavuzu",
    "electrical_diagram": "Elektrik Şeması",
    "hydraulic_diagram": "Hidrolik Şeması",
    "troubleshooting": "Arıza Teşhis ve Çözüm"
}

# Eski kategori -> yeni kategori mapping (geriye uyumluluk)
CATEGORY_MAPPING = {
    "parts": "parts_catalog",
    "service": "service_manual",
    "electrical": "electrical_diagram"
}


def get_category_terms(category: str, max_terms: int = 4) -> List[str]:
    """
    Kategori için arama terimlerini döndür
    
    Args:
        category: Kategori kodu
        max_terms: Maksimum terim sayısı (OR sorgusu için)
    
    Returns:
        Arama terimleri listesi
    """
    # Eski kategori adını yeniye çevir
    category = CATEGORY_MAPPING.get(category, category)
    
    terms = SEARCH_TERMS.get(category, SEARCH_TERMS["parts_catalog"])
    return terms[:max_terms]


def get_all_categories() -> Dict[str, str]:
    """Tüm kategorileri label'ları ile döndür"""
    return CATEGORY_LABELS.copy()


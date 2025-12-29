"""
Kategori ve Arama Terimleri - Çok Dilli Destek (TR, EN, RU, ZH)
"""
from typing import List, Dict

# Dil bazlı kategori arama terimleri
SEARCH_TERMS_BY_LANG: Dict[str, Dict[str, List[str]]] = {
    # İngilizce (EN)
    "en": {
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
    },
    
    # Türkçe (TR)
    "tr": {
        "parts_catalog": [
            "parça kataloğu",
            "yedek parça kataloğu",
            "parça kitabı",
            "eksplozyon şeması"
        ],
        "service_manual": [
            "servis kılavuzu",
            "tamir kılavuzu",
            "bakım kılavuzu",
            "atölye kılavuzu",
            "teknik kılavuz"
        ],
        "electrical_diagram": [
            "elektrik şeması",
            "kablo şeması",
            "elektrik devresi",
            "tesisat şeması",
            "devre şeması"
        ],
        "hydraulic_diagram": [
            "hidrolik şema",
            "hidrolik devre şeması",
            "hidrolik sistem şeması"
        ],
        "troubleshooting": [
            "arıza kodu",
            "hata kodu listesi",
            "arıza teşhis",
            "sorun giderme",
            "DTC kodları"
        ]
    },
    
    # Rusça (RU)
    "ru": {
        "parts_catalog": [
            "каталог запчастей",
            "каталог деталей",
            "список запчастей",
            "справочник деталей"
        ],
        "service_manual": [
            "руководство по ремонту",
            "руководство по обслуживанию",
            "сервисное руководство",
            "руководство по эксплуатации"
        ],
        "electrical_diagram": [
            "электрическая схема",
            "схема электропроводки",
            "электросхема"
        ],
        "hydraulic_diagram": [
            "гидравлическая схема",
            "схема гидравлики"
        ],
        "troubleshooting": [
            "коды ошибок",
            "диагностика неисправностей",
            "руководство по устранению неисправностей"
        ]
    },
    
    # Çince (ZH)
    "zh": {
        "parts_catalog": [
            "零件目录",
            "配件手册",
            "备件目录",
            "零件手册"
        ],
        "service_manual": [
            "维修手册",
            "服务手册",
            "修理手册",
            "保养手册"
        ],
        "electrical_diagram": [
            "电气图",
            "线路图",
            "电路图"
        ],
        "hydraulic_diagram": [
            "液压图",
            "液压原理图"
        ],
        "troubleshooting": [
            "故障代码",
            "故障诊断",
            "错误代码"
        ]
    }
}

# Geriye uyumluluk için - varsayılan İngilizce terimler
SEARCH_TERMS = SEARCH_TERMS_BY_LANG["en"]

# Türkçe kategori isimleri (Frontend için)
CATEGORY_LABELS: Dict[str, str] = {
    "parts_catalog": "Parça Kataloğu",
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

# Desteklenen diller
SUPPORTED_LANGUAGES = {
    "en": "English",
    "tr": "Türkçe",
    "ru": "Русский",
    "zh": "中文"
}


def get_category_terms(category: str, max_terms: int = 4, language: str = "en") -> List[str]:
    """
    Kategori için arama terimlerini döndür
    
    Args:
        category: Kategori kodu
        max_terms: Maksimum terim sayısı (OR sorgusu için)
        language: Dil kodu (en, tr, ru, zh)
    
    Returns:
        Arama terimleri listesi
    """
    # Eski kategori adını yeniye çevir
    category = CATEGORY_MAPPING.get(category, category)
    
    # Dil için terimleri al
    lang_terms = SEARCH_TERMS_BY_LANG.get(language, SEARCH_TERMS_BY_LANG["en"])
    terms = lang_terms.get(category, lang_terms.get("parts_catalog", []))
    
    return terms[:max_terms]


def get_category_terms_all_langs(category: str, languages: List[str] = None) -> Dict[str, List[str]]:
    """
    Belirtilen diller için kategori terimlerini döndür
    
    Args:
        category: Kategori kodu
        languages: Dil kodları listesi (None = tümü)
    
    Returns:
        {lang: [terms]} şeklinde dict
    """
    if languages is None:
        languages = list(SEARCH_TERMS_BY_LANG.keys())
    
    # Eski kategori adını yeniye çevir
    category = CATEGORY_MAPPING.get(category, category)
    
    result = {}
    for lang in languages:
        if lang in SEARCH_TERMS_BY_LANG:
            lang_terms = SEARCH_TERMS_BY_LANG[lang]
            result[lang] = lang_terms.get(category, lang_terms.get("parts_catalog", []))
    
    return result


def get_all_categories() -> Dict[str, str]:
    """Tüm kategorileri label'ları ile döndür"""
    return CATEGORY_LABELS.copy()


def get_supported_languages() -> Dict[str, str]:
    """Desteklenen dilleri döndür"""
    return SUPPORTED_LANGUAGES.copy()

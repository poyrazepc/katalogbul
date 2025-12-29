"""
PDF Boyut Filtreleme

Kullanıcının seçtiği boyut aralığına göre sonuçları filtrele.
"""
from typing import List, Dict, Tuple, Optional
import math


# Boyut preset'leri (MB cinsinden)
SIZE_PRESETS: Dict[str, Tuple[float, float]] = {
    "all": (0, math.inf),           # Tüm boyutlar
    "1mb+": (1, math.inf),          # 1 MB ve üzeri
    "5mb+": (5, math.inf),          # 5 MB ve üzeri
    "10mb+": (10, math.inf),        # 10 MB ve üzeri
    "20mb+": (20, math.inf),        # 20 MB ve üzeri
    "50mb+": (50, math.inf),        # 50 MB ve üzeri
    "small": (0, 5),                # 5 MB'dan küçük
    "medium": (5, 20),              # 5-20 MB arası
    "large": (20, math.inf),        # 20 MB ve üzeri
}

# Türkçe label'lar
SIZE_LABELS: Dict[str, str] = {
    "all": "Tüm Boyutlar",
    "1mb+": "1 MB+",
    "5mb+": "5 MB+",
    "10mb+": "10 MB+",
    "20mb+": "20 MB+",
    "50mb+": "50 MB+",
    "small": "Küçük (< 5 MB)",
    "medium": "Orta (5-20 MB)",
    "large": "Büyük (> 20 MB)",
}


def format_file_size(size_bytes: Optional[int]) -> str:
    """
    Byte'ı okunabilir formata çevir
    
    Args:
        size_bytes: Dosya boyutu (byte)
    
    Returns:
        "12.5 MB" gibi okunabilir format
    """
    if size_bytes is None:
        return "Bilinmiyor"
    
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def filter_by_size(
    results: List[Dict],
    size_filter: str = "all",
    include_unknown: bool = True
) -> List[Dict]:
    """
    Sonuçları boyuta göre filtrele
    
    Args:
        results: Arama sonuçları (size_mb alanı olmalı)
        size_filter: Boyut filtresi (all, 1mb+, 5mb+, vb.)
        include_unknown: Boyutu bilinmeyen sonuçları dahil et
    
    Returns:
        Filtrelenmiş sonuçlar
    """
    if size_filter == "all":
        return results
    
    min_mb, max_mb = SIZE_PRESETS.get(size_filter, (0, math.inf))
    
    filtered = []
    for result in results:
        size_mb = result.get("size_mb")
        
        if size_mb is None:
            if include_unknown:
                filtered.append(result)
            continue
        
        if min_mb <= size_mb <= max_mb:
            filtered.append(result)
    
    return filtered


def filter_by_custom_range(
    results: List[Dict],
    min_mb: float = 0,
    max_mb: float = math.inf,
    include_unknown: bool = True
) -> List[Dict]:
    """
    Özel boyut aralığına göre filtrele
    
    Args:
        results: Arama sonuçları
        min_mb: Minimum boyut (MB)
        max_mb: Maksimum boyut (MB)
        include_unknown: Boyutu bilinmeyen sonuçları dahil et
    
    Returns:
        Filtrelenmiş sonuçlar
    """
    filtered = []
    for result in results:
        size_mb = result.get("size_mb")
        
        if size_mb is None:
            if include_unknown:
                filtered.append(result)
            continue
        
        if min_mb <= size_mb <= max_mb:
            filtered.append(result)
    
    return filtered


def get_size_distribution(results: List[Dict]) -> Dict[str, int]:
    """
    Sonuçların boyut dağılımını hesapla
    
    Args:
        results: Arama sonuçları
    
    Returns:
        {"small": 10, "medium": 25, "large": 15, "unknown": 5}
    """
    distribution = {
        "small": 0,      # < 5 MB
        "medium": 0,     # 5-20 MB
        "large": 0,      # > 20 MB
        "unknown": 0
    }
    
    for result in results:
        size_mb = result.get("size_mb")
        
        if size_mb is None:
            distribution["unknown"] += 1
        elif size_mb < 5:
            distribution["small"] += 1
        elif size_mb < 20:
            distribution["medium"] += 1
        else:
            distribution["large"] += 1
    
    return distribution


def get_available_filters() -> List[Dict[str, str]]:
    """
    Frontend için kullanılabilir filtre listesi
    
    Returns:
        [{"value": "all", "label": "Tüm Boyutlar"}, ...]
    """
    return [
        {"value": key, "label": SIZE_LABELS[key]}
        for key in ["all", "1mb+", "5mb+", "10mb+", "20mb+"]
    ]


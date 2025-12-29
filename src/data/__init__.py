"""
PDF Katalog Arama Sistemi - Veri Modülleri
"""
from .brands import BRAND_LIST, BRAND_ALIASES, get_brand_aliases
from .categories import SEARCH_TERMS, CATEGORY_LABELS, get_category_terms
from .domains import PREMIUM_DOMAINS, EXCLUDED_DOMAINS, is_premium_domain, is_excluded_domain

__all__ = [
    'BRAND_LIST',
    'BRAND_ALIASES', 
    'get_brand_aliases',
    'SEARCH_TERMS',
    'CATEGORY_LABELS',
    'get_category_terms',
    'PREMIUM_DOMAINS',
    'EXCLUDED_DOMAINS',
    'is_premium_domain',
    'is_excluded_domain'
]


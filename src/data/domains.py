"""
Domain Listeleri - Premium ve Hariç Tutulan Siteler
"""
from typing import List

# Premium platformlar (ücretli/kayıt gerektiren)
PREMIUM_DOMAINS: List[str] = [
    # Doküman Paylaşım Platformları
    "scribd.com",
    "issuu.com",
    "academia.edu",
    "researchgate.net",
    "slideshare.net",
    "calameo.com",
    "yumpu.com",
    
    # PDF Platformları
    "pdfcoffee.com",
    "pdfdrive.com",
    "pdfslide.net",
    "dokumen.tips",
    "fdocuments.net",
    "vdocuments.net",
    "cupdf.com",
    "vsepdf.com",
    "manualzz.com",
    
    # Çin Platformları
    "wenku.baidu.com",
    "docin.com",
    "book118.com",
    "doc88.com",
    "360doc.com",
    "max.book118.com",
    
    # Rusya Platformları
    "studfile.net",
    "topuch.ru",
    "studopedia.ru",
    
    # Diğer
    "slideshare.jp",
    "happycampus.com"
]

# Ticari/Satış siteleri - aramadan hariç tut
EXCLUDED_DOMAINS: List[str] = [
    # E-ticaret
    "ebay.com",
    "ebay.de",
    "ebay.co.uk",
    "ebay.fr",
    "amazon.com",
    "amazon.de",
    "amazon.co.uk",
    "aliexpress.com",
    "alibaba.com",
    
    # Manuel satış siteleri
    "autoepcservice.com",
    "epcatalogs.com",
    "heavymanuals.com",
    "themanualman.com",
    "sellfy.com",
    "payhip.com",
    
    # Spam/düşük kalite
    "pinterest.com",
    "facebook.com",
    "twitter.com",
    "youtube.com"
]


def is_premium_domain(url: str) -> bool:
    """URL'nin premium platform olup olmadığını kontrol et"""
    url_lower = url.lower()
    return any(domain in url_lower for domain in PREMIUM_DOMAINS)


def is_excluded_domain(url: str) -> bool:
    """URL'nin hariç tutulan site olup olmadığını kontrol et"""
    url_lower = url.lower()
    return any(domain in url_lower for domain in EXCLUDED_DOMAINS)


def get_domain_from_url(url: str) -> str:
    """URL'den domain çıkar"""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except Exception:
        return ""


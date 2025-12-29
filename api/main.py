from dotenv import load_dotenv
load_dotenv()  # .env dosyasını yükle

from fastapi import FastAPI, BackgroundTasks, Query, HTTPException, Request, Depends, Form, Body
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import os
import asyncio
import json
import logging
from src.database import PEPCDatabase
from src.pepc_discovery import PEPCDiscovery
from src.serper_client import SerperClient
from src.multi_search import MultiSearchCoordinator
from src.keywords import DOCUMENT_KEYWORDS, PREMIUM_SITES, EXCLUDED_DOMAINS
from src.utils import setup_logging, get_multiple_pdf_sizes, extract_brand_from_query, map_doc_type_to_category, get_category_label
from src.config import THUMBNAIL_DIR, SEARCH_ENGINES, DATABASE_PATH

# Yeni modüler yapı
from src.data.brands import BRAND_LIST, BRAND_ALIASES, get_brand_aliases
from src.data.categories import SEARCH_TERMS, CATEGORY_LABELS, get_category_terms, get_all_categories
from src.data.domains import PREMIUM_DOMAINS, is_premium_domain, is_excluded_domain
from src.search.query_builder import build_search_query, build_or_clause
from src.search.aggregator import MultiEngineAggregator, get_aggregator
from src.pdf.head_checker import get_bulk_pdf_info, enrich_results_with_size
from src.pdf.size_filter import SIZE_PRESETS, filter_by_size, get_available_filters

# Auth ve Kredi Sistemi
from src.auth import get_user_manager, create_access_token, UserManager
from src.models import UserRegister, UserLogin, Token, UserResponse, PaymentCreate
from src.dependencies import (
    get_current_user_optional, get_current_user, get_admin_user,
    get_client_ip, get_user_agent
)
from src.credit_manager import get_credit_manager, CreditManager
from src.settings_manager import get_settings_manager, SettingsManager
from src.payment import get_paytr_client, PayTRClient, PACKAGES
from pydantic import BaseModel

setup_logging()

# Global logger (endpoint'lerde kullanılacak)
logger = logging.getLogger(__name__)

app = FastAPI(title="KatalogBul API", version="2.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = PEPCDatabase()
discovery = PEPCDiscovery()

# Managers
user_manager = get_user_manager()
credit_manager = get_credit_manager()
settings_manager = get_settings_manager()
paytr_client = get_paytr_client()

# Statik dosyaları sunmak için frontend klasörünü bağla
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_index():
    return FileResponse("frontend/index.html")

@app.get("/auth.html", response_class=HTMLResponse)
async def read_auth():
    return FileResponse("frontend/auth.html")

@app.get("/search.html", response_class=HTMLResponse)
async def read_search():
    return FileResponse("frontend/search.html")

@app.get("/saved-searches.html", response_class=HTMLResponse)
async def read_saved_searches():
    return FileResponse("frontend/saved-searches.html")

@app.get("/dashboard.html", response_class=HTMLResponse)
async def read_dashboard():
    return FileResponse("frontend/dashboard.html")

@app.get("/contact.html", response_class=HTMLResponse)
async def read_contact():
    return FileResponse("frontend/contact.html")

@app.get("/admin", response_class=HTMLResponse)
async def read_admin():
    return FileResponse("frontend/admin.html")

@app.get("/catalog-viewer.html", response_class=HTMLResponse)
async def read_catalog_viewer():
    return FileResponse("frontend/catalog-viewer.html")

@app.get("/login.html", response_class=HTMLResponse)
async def read_login():
    return FileResponse("frontend/login.html")

@app.get("/register.html", response_class=HTMLResponse)
async def read_register():
    return FileResponse("frontend/register.html")

@app.get("/forgot-password.html", response_class=HTMLResponse)
async def read_forgot_password():
    return FileResponse("frontend/forgot-password.html")


# =============================================================================
# CATALOG VIEWER API - Parts Catalog Görüntüleyici
# =============================================================================

from src.catalog_analyzer import CatalogAnalyzer
from fastapi.responses import StreamingResponse
import io

# Global catalog instance (demo için)
_current_catalog = None

@app.post("/api/catalog/load")
async def load_catalog(pdf_path: str = "503976932-DYNAPAC-CA2500D-PARTS-MANUAL.pdf", toc_start: int = 3, toc_end: int = 8):
    """PDF kataloğunu yükle ve analiz et"""
    global _current_catalog
    
    try:
        full_path = f"C:/xampp/htdocs/pdfara/{pdf_path}"
        _current_catalog = CatalogAnalyzer(full_path)
        
        analysis = _current_catalog.analyze_structure(toc_start=toc_start, toc_end=toc_end)
        
        return {
            "success": True,
            "catalog": analysis
        }
    except Exception as e:
        raise HTTPException(500, f"Katalog yüklenemedi: {str(e)}")


@app.get("/api/catalog/page/{page_num}/parts")
async def get_page_parts(page_num: int):
    """Belirli bir sayfadaki parçaları al - ÇİFT SAYFA (tablo sayfası)"""
    if not _current_catalog:
        raise HTTPException(400, "Önce katalog yüklenmelidir")
    
    try:
        # Eğer tek sayfa geldiyse, bir sonraki çift sayfayı kullan
        table_page = page_num + 1 if page_num % 2 == 1 else page_num
        
        parts_data = _current_catalog.extract_page_parts(table_page)
        return parts_data
    except Exception as e:
        raise HTTPException(500, f"Parçalar çıkarılamadı: {str(e)}")


@app.get("/api/catalog/page/{page_num}/image")
async def get_page_image(page_num: int, zoom: float = 2.0):
    """Sayfa görselini al - TEK SAYFA (diyagram sayfası)"""
    if not _current_catalog:
        raise HTTPException(400, "Önce katalog yüklenmelidir")
    
    try:
        # Eğer çift sayfa geldiyse, bir önceki tek sayfayı kullan
        diagram_page = page_num - 1 if page_num % 2 == 0 else page_num
        
        img_bytes = _current_catalog.get_page_image(diagram_page, zoom)
        return StreamingResponse(io.BytesIO(img_bytes), media_type="image/png")
    except Exception as e:
        raise HTTPException(500, f"Görsel oluşturulamadı: {str(e)}")


class DiscoveryRequest(BaseModel):
    brands: List[str]
    doc_types: Optional[List[str]] = ["parts_catalog"]
    languages: Optional[List[str]] = ["en", "tr"]
    equipment_types: Optional[List[str]] = None

class LiveSearchRequest(BaseModel):
    brand: str
    model: Optional[str] = None
    doc_type: str = "parts_catalog"
    languages: Optional[List[str]] = None  # None = tüm diller

async def worker():
    """Arka planda kuyruğu işleyen worker"""
    while True:
        try:
            await discovery.process_queue()
        except Exception as e:
            print(f"Worker hatası: {e}")
            await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(worker())

def is_premium_site(url):
    """URL'nin premium site olup olmadığını kontrol et"""
    return is_premium_domain(url)

def is_excluded_site(url):
    """URL'nin hariç tutulan site olup olmadığını kontrol et"""
    return is_excluded_domain(url)

def is_promotional_content(title, snippet):
    """Tanıtım/reklam içeriği kontrolü"""
    promo_keywords = [
        "brochure", "broşür", "product range", "product line",
        "sales", "satış", "buy now", "order now", "pricing",
        "company profile", "about us", "hakkımızda",
        "product overview", "specifications overview",
        "katalog ürün", "ürün kataloğu", "product catalog brochure"
    ]
    text = (title + " " + (snippet or "")).lower()
    
    # Parça numarası içeriyorsa, tanıtım değildir
    if "part number" in text or "part no" in text or "p/n" in text:
        return False
    
    for kw in promo_keywords:
        if kw in text:
            return True
    return False

def check_brand_match(brand: str, title: str, snippet: str, url: str) -> bool:
    """Marka adının sonuçta geçip geçmediğini kontrol et"""
    brand_lower = brand.lower().strip()
    text = (title + " " + (snippet or "") + " " + url).lower()
    
    # Ana marka adı kontrolü
    if brand_lower in text:
        return True
    
    # Marka varyasyonları (CAT = Caterpillar, vb.)
    brand_aliases = {
        "caterpillar": ["cat", "caterpillar"],
        "cat": ["cat", "caterpillar"],
        "komatsu": ["komatsu", "komats"],
        "hitachi": ["hitachi", "hitachi-c"],
        "volvo": ["volvo", "volvo ce"],
        "jcb": ["jcb"],
        "liebherr": ["liebherr"],
        "doosan": ["doosan", "daewoo"],
        "hyundai": ["hyundai", "hce"],
        "kobelco": ["kobelco"],
        "case": ["case", "case ih", "caseih"],
        "john deere": ["john deere", "deere", "jd"],
        "kubota": ["kubota"],
        "bobcat": ["bobcat"],
        "takeuchi": ["takeuchi"],
        "yanmar": ["yanmar"],
        "ihi": ["ihi"],
        "sumitomo": ["sumitomo"],
        "hidromek": ["hidromek"],
        "xcmg": ["xcmg"],
        "sany": ["sany"],
        "zoomlion": ["zoomlion"],
        "liugong": ["liugong"],
        "shantui": ["shantui"],
    }
    
    # Alias kontrolü
    aliases = brand_aliases.get(brand_lower, [brand_lower])
    for alias in aliases:
        if alias in text:
            return True
    
    return False

# Kategori grupları - frontend'den gelen grup adına göre hangi doc_type'lar aranacak
DOC_TYPE_GROUPS = {
    "parts": ["parts_catalog", "parts_book", "parts_manual", "parts_list"],
    "service": ["repair_manual", "workshop_manual", "shop_manual"],
    "electrical": ["wiring_diagram", "hydraulic_diagram", "troubleshooting"]
}

# İçerik arama terimleri
CONTENT_TERMS = {
    "parts_catalog": "part number",
    "parts_book": "part number",
    "parts_manual": "part number",
    "parts_list": "item number",
    "repair_manual": "repair procedure",
    "workshop_manual": "service manual",
    "shop_manual": "shop manual",
    "wiring_diagram": "wiring diagram",
    "hydraulic_diagram": "hydraulic diagram",
    "troubleshooting": "fault code"
}

@app.post("/live-search")
async def live_search(request: LiveSearchRequest):
    """İnternette çok dilli canlı arama - Premium siteler hariç"""
    client = SerperClient()
    
    # Sadece İngilizce arama
    all_languages = ["en"]
    languages = request.languages if request.languages else all_languages
    
    all_results = []
    seen_urls = set()
    
    # Grup adından doc_type listesini al
    doc_types = DOC_TYPE_GROUPS.get(request.doc_type, [request.doc_type])
    
    # Elektrik/şema grubu mu kontrol et (boyut filtresi için)
    is_diagram_search = request.doc_type == "electrical"
    
    try:
        for doc_type in doc_types:
            doc_keywords = DOCUMENT_KEYWORDS.get(doc_type, {})
            content_term = CONTENT_TERMS.get(doc_type, "part number")
            
            for lang in languages:
                keywords = doc_keywords.get(lang, doc_keywords.get("en", ["parts catalog"]))
                keyword = keywords[0] if keywords else "parts catalog"
                
                # Sorgu 1: Marka + keyword + model
                query1 = f"{request.brand} {keyword}"
                if request.model:
                    query1 += f" {request.model}"
                
                # Sorgu 2: Marka + model + içerik terimi
                query2 = f"{request.brand} {content_term}"
                if request.model:
                    query2 += f" {request.model}"
                
                for query in [query1, query2]:
                    results = await client.search_pdfs(query=query, num=15, hl=lang)
                    
                    for r in results:
                        if r.url not in seen_urls and not is_premium_site(r.url) and not is_excluded_site(r.url):
                            if not is_promotional_content(r.title, r.snippet):
                                seen_urls.add(r.url)
                                brand_match = check_brand_match(request.brand, r.title, r.snippet, r.url)
                                all_results.append({
                                    "title": r.title,
                                    "url": r.url,
                                    "snippet": r.snippet,
                                    "domain": r.domain,
                                    "language": lang,
                                    "doc_type": doc_type,
                                    "is_diagram": is_diagram_search,
                                    "brand_match": brand_match
                                })
        
        # Önce marka eşleşenler, sonra diğerleri
        all_results.sort(key=lambda x: (0 if x['brand_match'] else 1, 0 if x['language'] == 'en' else 1))
        
        # Dosya boyutlarını paralel olarak al
        if all_results:
            urls = [r['url'] for r in all_results]
            sizes = await get_multiple_pdf_sizes(urls)
            for result in all_results:
                result['file_size'] = sizes.get(result['url'])
        
        return all_results
    finally:
        await client.close()

@app.post("/premium-search")
async def premium_search(request: LiveSearchRequest):
    """Premium sitelerde (Scribd, Issuu, vb.) arama"""
    client = SerperClient()
    
    # Sadece İngilizce arama
    all_languages = ["en"]
    languages = request.languages if request.languages else all_languages
    
    all_results = []
    seen_urls = set()
    
    # Grup adından doc_type listesini al
    doc_types = DOC_TYPE_GROUPS.get(request.doc_type, [request.doc_type])
    is_diagram_search = request.doc_type == "electrical"
    
    premium_sites_to_search = [
        ("Scribd", "site:scribd.com"),
        ("Issuu", "site:issuu.com"),
        ("PDFCoffee", "site:pdfcoffee.com"),
        ("Calameo", "site:calameo.com"),
        ("SlideShare", "site:slideshare.net"),
        ("Academia", "site:academia.edu"),
        ("Manualzz", "site:manualzz.com"),
        ("Yumpu", "site:yumpu.com"),
        ("Baidu", "site:wenku.baidu.com"),
        ("Docin", "site:docin.com"),
    ]
    
    try:
        for doc_type in doc_types:
            doc_keywords = DOCUMENT_KEYWORDS.get(doc_type, {})
            
            for lang in languages:
                keywords = doc_keywords.get(lang, doc_keywords.get("en", ["parts catalog"]))
                keyword = keywords[0] if keywords else "parts catalog"
                
                for platform_name, site_query in premium_sites_to_search:
                    base_query = f"{request.brand} {keyword}"
                    if request.model:
                        base_query = f"{request.brand} {request.model} {keyword}"
                    
                    query = f"{base_query} {site_query}"
                    
                    results = await client.search_general(query=query, num=8, hl=lang)
                    
                    for r in results:
                        if r.url not in seen_urls:
                            if not is_promotional_content(r.title, r.snippet):
                                seen_urls.add(r.url)
                                brand_match = check_brand_match(request.brand, r.title, r.snippet, r.url)
                                all_results.append({
                                    "title": r.title,
                                    "url": r.url,
                                    "snippet": r.snippet,
                                    "domain": r.domain,
                                    "language": lang,
                                    "platform": platform_name,
                                    "doc_type": doc_type,
                                    "is_diagram": is_diagram_search,
                                    "brand_match": brand_match
                                })
        
        # Önce marka eşleşenler
        all_results.sort(key=lambda x: (0 if x['brand_match'] else 1, 0 if x['language'] == 'en' else 1))
        
        # Dosya boyutlarını paralel olarak al
        if all_results:
            urls = [r['url'] for r in all_results]
            sizes = await get_multiple_pdf_sizes(urls)
            for result in all_results:
                result['file_size'] = sizes.get(result['url'])
        
        return all_results
    finally:
        await client.close()

class ScanSourceRequest(BaseModel):
    url: str

class GlobalSearchRequest(BaseModel):
    query: str
    languages: Optional[List[str]] = None

@app.post("/global-search")
async def global_search(request: GlobalSearchRequest):
    """Serbest metin ile global PDF araması - iş makinaları odaklı"""
    client = SerperClient()
    
    all_languages = ["en"]
    languages = request.languages if request.languages else all_languages
    
    all_results = []
    seen_urls = set()
    
    # İş makinaları odaklı arama için ek terimler
    machinery_terms = ["heavy equipment", "construction", "excavator", "loader", "bulldozer", "crane", "forklift"]
    
    try:
        for lang in languages:
            # Ana sorgu
            query = f"{request.query} filetype:pdf"
            results = await client.search_pdfs(query=query, num=20, hl=lang)
            
            for r in results:
                if r.url not in seen_urls and not is_excluded_site(r.url):
                    seen_urls.add(r.url)
                    all_results.append({
                        "title": r.title,
                        "url": r.url,
                        "snippet": r.snippet,
                        "domain": r.domain,
                        "language": lang
                    })
        
        # Boyutları al
        if all_results:
            urls = [r['url'] for r in all_results]
            sizes = await get_multiple_pdf_sizes(urls)
            for result in all_results:
                result['file_size'] = sizes.get(result['url'])
        
        # Boyuta göre sırala
        all_results.sort(key=lambda x: (x.get('file_size') or 0), reverse=True)
        
        return all_results
    finally:
        await client.close()

@app.post("/api/scan-source")
async def scan_source(request: ScanSourceRequest):
    """Bir PDF'in bulunduğu kaynaktaki tüm PDF'leri tara - sayfalama ile maksimum sonuç"""
    from urllib.parse import urlparse, unquote
    import logging
    
    logger = logging.getLogger(__name__)
    client = SerperClient()
    all_results = []
    seen_urls = set()
    
    try:
        # URL'den domain ve path çıkar
        parsed = urlparse(unquote(request.url))
        domain = parsed.netloc
        
        # Path'i klasöre düşür
        path_parts = parsed.path.rsplit('/', 1)
        base_path = path_parts[0] if len(path_parts) > 1 else ""
        
        # Farklı arama stratejileri
        search_queries = []
        
        # 1. Ana domain araması (en geniş)
        search_queries.append({
            "query": f"site:{domain} pdf",
            "label": f"site:{domain}"
        })
        
        # 2. Path içeren arama (eğer path varsa)
        if base_path:
            path_keywords = [p for p in base_path.split('/') if p and len(p) > 2]
            if path_keywords:
                keywords = ' '.join(path_keywords[-2:])
                search_queries.insert(0, {
                    "query": f"site:{domain} {keywords} pdf",
                    "label": f"site:{domain} + {keywords}"
                })
        
        # 3. Sadece filetype:pdf ile
        search_queries.append({
            "query": f"site:{domain} filetype:pdf",
            "label": f"site:{domain} filetype:pdf"
        })
        
        # Sayfalama: Her sorgu için 5 sayfa (5 x 20 = 100 sonuç per query)
        pages_to_fetch = 5
        results_per_page = 20
        
        scanned_levels = []
        for sq in search_queries:
            query = sq["query"]
            label = sq["label"]
            level_count = 0
            
            # Her sayfa için ayrı istek
            for page in range(pages_to_fetch):
                start = page * results_per_page
                
                logger.info(f"Kaynak tarama: {query} (sayfa {page + 1}, start={start})")
                
                # Sayfalama için start parametresi ekle
                results = await client.search_general(
                    query=query, 
                    num=results_per_page, 
                    hl="en",
                    start=start
                )
                
                # Sonuç yoksa bu sorgu için dur
                if not results:
                    logger.info(f"  -> Sayfa {page + 1}: sonuç yok, durduruluyor")
                    break
                
                page_count = 0
                for r in results:
                    if r.url not in seen_urls and '.pdf' in r.url.lower():
                        seen_urls.add(r.url)
                        level_count += 1
                        page_count += 1
                        all_results.append({
                            "title": r.title,
                            "url": r.url,
                            "snippet": r.snippet,
                            "domain": r.domain,
                            "found_in": label
                        })
                
                logger.info(f"  -> Sayfa {page + 1}: {page_count} yeni PDF")
                
                # Rate limiting için kısa bekleme
                await asyncio.sleep(0.3)
            
            scanned_levels.append({"pattern": label, "found": level_count})
            logger.info(f"Toplam {label}: {level_count} PDF")
        
        # Boyutları al
        if all_results:
            urls = [r['url'] for r in all_results]
            sizes = await get_multiple_pdf_sizes(urls)
            for result in all_results:
                result['file_size'] = sizes.get(result['url'])
        
        # Boyuta göre sırala
        all_results.sort(key=lambda x: (x.get('file_size') or 0), reverse=True)
        
        return {
            "source": domain,
            "base_path": base_path,
            "levels_scanned": len(search_queries),
            "pages_per_query": pages_to_fetch,
            "scanned_levels": scanned_levels,
            "count": len(all_results),
            "results": all_results
        }
    finally:
        await client.close()

@app.get("/search")
async def search_database(
    brand: Optional[str] = None,
    doc_type: Optional[str] = None,
    language: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = Query(20, le=100),
    offset: int = 0
):
    """Veritabanında arama yap (kayıtlı PDF'ler)"""
    filters = {
        "brand": brand,
        "doc_type": doc_type,
        "language": language,
        "title": keyword
    }
    results = db.search_catalog(filters, limit, offset)
    return results

@app.post("/discover")
async def start_discovery(request: DiscoveryRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(
        discovery.run_discovery,
        brands=request.brands,
        doc_types=request.doc_types,
        equipment_types=request.equipment_types,
        languages=request.languages
    )
    return {"message": "Keşif süreci arka planda başlatıldı."}

@app.get("/tasks")
async def get_tasks(limit: int = 10):
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM task_queue ORDER BY created_at DESC LIMIT ?", (limit,))
    tasks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return tasks

@app.get("/thumbnail/{pdf_id}")
async def get_thumbnail(pdf_id: int):
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT thumbnail_path FROM pdf_catalog WHERE id = ?", (pdf_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not row['thumbnail_path']:
        raise HTTPException(status_code=404, detail="Thumbnail bulunamadı")
        
    path = row['thumbnail_path']
    if os.path.exists(path):
        return FileResponse(path)
    else:
        raise HTTPException(status_code=404, detail="Thumbnail dosyası fiziksel olarak yok")

@app.get("/stats")
async def get_stats():
    conn = db.get_connection()
    cursor = conn.cursor()
    
    stats = {}
    cursor.execute("SELECT COUNT(*) FROM pdf_catalog")
    stats['total_pdfs'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT status, COUNT(*) FROM pdf_catalog GROUP BY status")
    stats['status_distribution'] = dict(cursor.fetchall())
    
    cursor.execute("SELECT COUNT(*) FROM task_queue WHERE status = 'pending'")
    stats['pending_tasks'] = cursor.fetchone()[0]
    
    conn.close()
    return stats


# =============================================================================
# MULTI-ENGINE SEARCH API
# =============================================================================

class MultiSearchRequest(BaseModel):
    brand: Optional[str] = None
    model: Optional[str] = None
    query_text: Optional[str] = None  # Serbest metin arama
    category: str = "parts_catalog"  # Yeni 5 kategori sistemi
    doc_type: str = "parts"  # Geriye uyumluluk için
    languages: Optional[List[str]] = None
    engines: Optional[List[str]] = None  # None = tüm motorlar
    use_cache: bool = True
    size_filter: str = "all"  # Boyut filtresi: all, 1mb+, 5mb+, 10mb+, 20mb+
    page: int = 1
    per_page: int = 20  # Sayfa başına sonuç

class MultiScanRequest(BaseModel):
    url: str
    engines: Optional[List[str]] = None

# Global multi-search coordinator
multi_search_coordinator: Optional[MultiSearchCoordinator] = None

@app.on_event("startup")
async def init_multi_search():
    global multi_search_coordinator
    multi_search_coordinator = MultiSearchCoordinator(use_cache=True)

@app.on_event("shutdown")
async def cleanup_multi_search():
    global multi_search_coordinator
    if multi_search_coordinator:
        await multi_search_coordinator.close()

@app.get("/engines")
async def get_available_engines():
    """Kullanılabilir arama motorlarını listele"""
    return {
        "engines": SEARCH_ENGINES,
        "active": [name for name, config in SEARCH_ENGINES.items() if config.get("enabled", True)]
    }

@app.get("/api/brands")
async def get_available_brands():
    """Kullanılabilir marka listesini döndür"""
    return {
        "brands": BRAND_LIST,
        "count": len(BRAND_LIST)
    }


@app.get("/api/categories")
async def get_categories():
    """Kullanılabilir kategorileri döndür"""
    return {
        "categories": get_all_categories(),
        "count": len(CATEGORY_LABELS)
    }


@app.get("/api/size-filters")
async def get_size_filters():
    """Kullanılabilir boyut filtrelerini döndür"""
    return {
        "filters": get_available_filters()
    }

@app.post("/api/multi-search")
async def multi_engine_search(
    request: MultiSearchRequest,
    req: Request,
    user: dict = Depends(get_current_user_optional)
):
    """
    Çoklu arama motoru ile paralel PDF araması
    
    - Serper (Google)
    - Brave Search
    - Yandex
    - SearchApi (Bing)
    
    Sonuçlar 30 gün cache'lenir.
    """
    global multi_search_coordinator
    if not multi_search_coordinator:
        multi_search_coordinator = MultiSearchCoordinator(use_cache=True)
    
    # Sadece İngilizce arama
    all_languages = ["en"]
    languages = request.languages if request.languages else all_languages
    
    # Kategori bazlı arama (yeni sistem)
    # Geriye uyumluluk: doc_type -> category mapping
    category = request.category
    if request.doc_type and request.doc_type != "parts":
        category_map = {
            "parts": "parts_catalog",
            "service": "service_manual",
            "electrical": "electrical_diagram"
        }
        category = category_map.get(request.doc_type, request.category)
    
    is_diagram_search = category in ["electrical_diagram", "hydraulic_diagram"]
    
    all_engine_results = {}
    all_merged_results = []
    seen_urls = set()
    total_search_time = 0
    
    for lang in languages:
        # Her dil için ayrı sorgu oluştur (dil bazlı varyantlar)
        query = build_search_query(
            brand=request.brand,
            model=request.model or request.query_text,
            category=category,
            max_terms=4,
            engine="google",
            language=lang
        )
        
        # Multi-engine arama - Motor başına 50 sonuç limiti, sayfa bazlı cache
        result = await multi_search_coordinator.search_all_engines(
            query=query,
            count_per_engine=50,  # Her motor için 50 sonuç
            language=lang,
            doc_type=category,
            engines=request.engines,
            use_cache=request.use_cache,
            page=request.page  # Sayfa bazlı cache key
        )
                
        total_search_time += result.get("search_time", 0)
        
        # Motor sonuçlarını birleştir
        for engine_name, engine_result in result.get("engines", {}).items():
            if engine_name not in all_engine_results:
                all_engine_results[engine_name] = {
                    "engine": engine_name,
                    "engine_name": engine_result.get("engine_name", engine_name),
                    "results": [],
                    "count": 0,
                    "cached_count": 0
                }
            
            for r in engine_result.get("results", []):
                url = r.get("url", "").lower()
                # Premium site filtresi kaldırıldı - sadece excluded sites kontrol ediliyor
                if url not in seen_urls and not is_excluded_site(url):
                    seen_urls.add(url)
                    brand_match = check_brand_match(
                        request.brand or "", 
                        r.get("title", ""), 
                        r.get("description", ""), 
                        r.get("url", "")
                    ) if request.brand else True
                    
                    result_item = {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("description", ""),
                        "domain": r.get("url", "").split("/")[2] if "/" in r.get("url", "") else "",
                        "language": lang,
                        "category": category,
                        "doc_type": category,  # Geriye uyumluluk
                        "is_diagram": is_diagram_search,
                        "brand_match": brand_match,
                        "engine": engine_name
                    }
                    
                    all_engine_results[engine_name]["results"].append(result_item)
                    all_merged_results.append(result_item)
            
            all_engine_results[engine_name]["count"] = len(all_engine_results[engine_name]["results"])
            if engine_result.get("cached"):
                all_engine_results[engine_name]["cached_count"] += 1
    
    # Sıralama: Önce marka eşleşenler
    all_merged_results.sort(key=lambda x: (0 if x['brand_match'] else 1, 0 if x['language'] == 'en' else 1))
    
    # Dosya boyutlarını al
    if all_merged_results:
        urls = [r['url'] for r in all_merged_results]
        sizes = await get_multiple_pdf_sizes(urls)
        for result in all_merged_results:
            result['file_size'] = sizes.get(result['url'])
        
        # Motor bazlı sonuçlara da boyut ekle
        for engine_name in all_engine_results:
            for r in all_engine_results[engine_name]["results"]:
                r['file_size'] = sizes.get(r['url'])
    
    # Boyuta göre sırala
    all_merged_results.sort(key=lambda x: (x.get('file_size') or 0), reverse=True)
    
    # Boyut filtresi uygula
    if request.size_filter and request.size_filter != "all":
        all_merged_results = filter_by_size(all_merged_results, request.size_filter)
    
    # Toplam sonuç limiti: max 100
    all_merged_results = all_merged_results[:100]
    
    # Premium site araması ekle (Scribd, Issuu, vb.)
    premium_sites = [
        "scribd.com", "issuu.com", "pdfcoffee.com", "slideshare.net",
        "academia.edu", "manualzz.com", "yumpu.com", "calameo.com"
    ]
    
    # Premium arama için basit query oluştur
    premium_query_parts = []
    if request.brand:
        premium_query_parts.append(request.brand)
    if request.model:
        premium_query_parts.append(request.model)
    if request.query_text:
        premium_query_parts.append(request.query_text)
    
    # Kategori keyword ekle
    category_keywords = {
        "parts_catalog": "parts catalog",
        "service_manual": "service manual",
        "electrical_diagram": "wiring diagram",
        "hydraulic_diagram": "hydraulic diagram"
    }
    premium_query_parts.append(category_keywords.get(category, "parts catalog"))
    premium_base_query = " ".join(premium_query_parts)
    
    # Her premium site için arama yap (pagination ile)
    premium_search_results = []
    serper_client = SerperClient()
    
    try:
        for site in premium_sites:  # Tüm premium siteler
            site_query = f"site:{site} {premium_base_query}"
            
            # Pagination ile 50 sonuç al (5 sayfa x 10)
            for page in range(5):
                response = await serper_client.search(site_query, num=10, page=page+1)
                organic = response.get('organic', [])
                
                if not organic:
                    break
                
                for item in organic:
                    url = item.get('link', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        premium_search_results.append({
                            "title": item.get('title', ''),
                            "url": url,
                            "snippet": item.get('snippet', ''),
                            "domain": url.split('/')[2] if '/' in url else '',
                            "language": "en",
                            "category": category,
                            "doc_type": category,
                            "is_diagram": is_diagram_search,
                            "brand_match": True,
                            "engine": "serper",
                            "is_premium": True
                        })
                
                if len(organic) < 10:
                    break
    except Exception as e:
        print(f"Premium arama hatası: {e}")
    finally:
        await serper_client.close()
    
    # Premium ve normal sonuçları ayır
    premium_results = premium_search_results  # Premium site aramasından gelenler
    regular_results = []
    
    for result in all_merged_results:
        if is_premium_site(result.get('url', '')):
            result['is_premium'] = True
            premium_results.append(result)
        else:
            result['is_premium'] = False
            regular_results.append(result)
    
    # Sayfalama hesapla - Regular
    regular_total = len(regular_results)
    regular_total_pages = (regular_total + request.per_page - 1) // request.per_page if regular_total > 0 else 1
    regular_start = (request.page - 1) * request.per_page
    regular_end = regular_start + request.per_page
    regular_paginated = regular_results[regular_start:regular_end]
    
    # Sayfalama hesapla - Premium
    premium_total = len(premium_results)
    premium_total_pages = (premium_total + request.per_page - 1) // request.per_page if premium_total > 0 else 1
    premium_start = (request.page - 1) * request.per_page
    premium_end = premium_start + request.per_page
    premium_paginated = premium_results[premium_start:premium_end]
    
    # Arama sonuçlarını veritabanına kaydet (benzersiz PDF'ler)
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Tüm sonuçları kaydet (free + premium)
        all_to_save = regular_results + premium_results
        new_saved = 0
        
        for result in all_to_save:
            url = result.get('url', '')
            if not url:
                continue
            
            import hashlib
            url_hash = hashlib.md5(url.lower().split('?')[0].encode()).hexdigest()
            
            # Var mı kontrol et
            cursor.execute("SELECT id FROM discovered_pdfs WHERE url_hash = ?", (url_hash,))
            if cursor.fetchone():
                # Güncelle
                cursor.execute("""
                    UPDATE discovered_pdfs SET last_checked = CURRENT_TIMESTAMP WHERE url_hash = ?
                """, (url_hash,))
            else:
                # Yeni kayıt
                domain = url.split('/')[2] if '/' in url else ''
                cursor.execute("""
                    INSERT INTO discovered_pdfs 
                    (url_hash, url, title, domain, brand, model, category, is_valid)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """, (
                    url_hash, url, result.get('title', '')[:500], domain,
                    request.brand, request.model, category
                ))
                new_saved += 1
        
        conn.commit()
        logger.info(f"Arama sonuçları kaydedildi: {new_saved} yeni PDF")
    except Exception as e:
        logger.error(f"Sonuç kaydetme hatası: {e}")
    
    # Arama logunu veritabanına kaydet
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Kullanılan motorları JSON olarak kaydet
        engines_used = json.dumps(request.engines) if request.engines else json.dumps([])
        
        # IP adresi al
        ip_address = req.client.host if req.client else None
        user_agent = req.headers.get("user-agent", "")
        
        # Cache kullanıldı mı kontrol et
        is_cached = any(
            engine_data.get("cached_count", 0) > 0 
            for engine_data in all_engine_results.values()
        )
        
        cursor.execute("""
            INSERT INTO search_logs 
            (user_id, query, doc_type, engines_used, result_count, credits_used, is_cached, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user["id"] if user else None,
            (request.brand or request.query_text or "") + (" " + request.model if request.model else ""),
            request.doc_type,
            engines_used,
            len(all_merged_results),
            0,  # credits_used - şimdilik 0
            is_cached,
            ip_address,
            user_agent[:500] if user_agent else None  # Max 500 karakter
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Arama logu kaydetme hatası: {e}")
    
    # Tüm sonuçları birleştir (free + premium)
    all_combined_results = regular_results + premium_results
    
    # All results için de sayfalama
    all_total = len(all_combined_results)
    all_total_pages = (all_total + request.per_page - 1) // request.per_page if all_total > 0 else 1
    all_start = (request.page - 1) * request.per_page
    all_end = all_start + request.per_page
    all_paginated = all_combined_results[all_start:all_end]
    
    return {
            "query": {
                "brand": request.brand,
                "model": request.model,
                "query_text": request.query_text,
                "category": category,
                "doc_type": request.doc_type
            },
            "filters": {
                "size_filter": request.size_filter,
                "category": category
            },
            "counts": {
                "total": all_total,
                "free": regular_total,
                "premium": premium_total
            },
            "pagination": {
                "page": request.page,
                "per_page": request.per_page,
                "total_pages": all_total_pages
            },
            "engines": all_engine_results,
            "total": all_total,
            "results": all_merged_results,  # Tüm sonuçlar (geriye uyumluluk için)
            "all": {
                "results": all_paginated,
                "total": all_total,
                "page": request.page,
                "per_page": request.per_page,
                "total_pages": all_total_pages
            },
            "free": {
                "results": regular_paginated,
                "total": regular_total,
                "page": request.page,
                "per_page": request.per_page,
                "total_pages": regular_total_pages
            },
            "premium": {
                "results": premium_paginated,
                "total": premium_total,
                "page": request.page,
                "per_page": request.per_page,
                "total_pages": premium_total_pages
            },
            "regular": {  # Geriye uyumluluk için
                "results": regular_paginated,
                "total": regular_total,
                "page": request.page,
                "per_page": request.per_page,
                "total_pages": regular_total_pages
            },
            "search_time": total_search_time
        }

@app.post("/multi-scan-source")
async def multi_engine_scan_source(
    request: MultiScanRequest,
    req: Request,
    user: dict = Depends(get_current_user_optional)
):
    """Çoklu motor ile kaynak tarama"""
    global multi_search_coordinator
    
    if not multi_search_coordinator:
        multi_search_coordinator = MultiSearchCoordinator(use_cache=True)
    
    from urllib.parse import urlparse, unquote
    
    parsed = urlparse(unquote(request.url))
    domain = parsed.netloc
    path_parts = parsed.path.rsplit('/', 1)
    base_path = path_parts[0] if len(path_parts) > 1 else ""
    
    # Path'den anahtar kelimeler çıkar
    query = ""
    if base_path:
        path_keywords = [p for p in base_path.split('/') if p and len(p) > 2]
        if path_keywords:
            query = ' '.join(path_keywords[-2:])
    
    result = await multi_search_coordinator.search_site_all_engines(
        domain=domain,
        query=query,
        count_per_engine=30,
        engines=request.engines
    )
    
    # Boyutları al
    if result.get("merged_results"):
        urls = [r['url'] for r in result["merged_results"]]
        sizes = await get_multiple_pdf_sizes(urls)
        for r in result["merged_results"]:
            r['file_size'] = sizes.get(r['url'])
        
        # Boyuta göre sırala
        result["merged_results"].sort(key=lambda x: (x.get('file_size') or 0), reverse=True)
    
    # Kaynak tarama logunu veritabanına kaydet
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        engines_used = json.dumps(request.engines) if request.engines else json.dumps([])
        ip_address = req.client.host if req.client else None
        user_agent = req.headers.get("user-agent", "")
        
        cursor.execute("""
            INSERT INTO search_logs 
            (user_id, query, doc_type, engines_used, result_count, credits_used, is_cached, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user["id"] if user else None,
            f"site:{domain} {query}".strip(),
            "scan_source",
            engines_used,
            result.get("total_results", 0),
            0,
            False,
            ip_address,
            user_agent[:500] if user_agent else None
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Kaynak tarama logu kaydetme hatası: {e}")
    
    return {
        "source": domain,
        "base_path": base_path,
        "engines": result.get("engines", {}),
        "count": result.get("total_results", 0),
        "results": result.get("merged_results", []),
        "search_time": result.get("search_time", 0)
    }

@app.get("/cache/stats")
async def get_cache_stats():
    """Cache istatistiklerini getir"""
    global multi_search_coordinator
    
    if not multi_search_coordinator:
        return {"message": "Multi-search henüz başlatılmadı"}
    
    return multi_search_coordinator.get_cache_stats()

@app.post("/cache/clear")
async def clear_cache(engine: Optional[str] = None):
    """Cache temizle (tümü veya belirli motor)"""
    global multi_search_coordinator
    
    if not multi_search_coordinator:
        return {"message": "Multi-search henüz başlatılmadı", "cleared": 0}
    
    cleared = multi_search_coordinator.clear_cache(engine)
    return {
        "message": f"{'Tüm cache' if not engine else f'{engine} cache'} temizlendi",
        "cleared": cleared
    }

@app.post("/cache/refresh")
async def refresh_cache():
    """Süresi dolmuş cache kayıtlarını temizle"""
    global multi_search_coordinator
    
    if not multi_search_coordinator:
        return {"message": "Multi-search henüz başlatılmadı", "cleared": 0}
    
    cleared = multi_search_coordinator.refresh_cache()
    return {"message": "Süresi dolmuş cache temizlendi", "cleared": cleared}


# =============================================================================
# AUTH API - Kimlik Doğrulama
# =============================================================================

@app.post("/api/auth/register", response_model=Token)
async def register(data: UserRegister):
    """Yeni kullanıcı kaydı"""
    try:
        # Başlangıç kredisini ayarlardan al
        initial_credits = settings_manager.get_int("initial_credits", 50)
        
        user = user_manager.create_user(
            username=data.username,
            email=data.email,
            password=data.password,
            phone=data.phone,
            initial_credits=initial_credits
        )
        
        if not user:
            raise HTTPException(400, "Kullanıcı oluşturulamadı")
        
        # Token oluştur
        token = create_access_token(
            user_id=user["id"],
            email=user["email"],
            tier=user["subscription_tier"],
            role=user["role"]
        )
        
        return Token(access_token=token)
        
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/auth/login", response_model=Token)
async def login(data: UserLogin):
    """Kullanıcı girişi"""
    user = user_manager.authenticate(data.email, data.password)
    
    if not user:
        raise HTTPException(401, "E-posta veya şifre hatalı")
    
    token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        tier=user["subscription_tier"],
        role=user["role"]
    )
    
    return Token(access_token=token)


@app.get("/api/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Mevcut kullanıcı bilgisi"""
    # Şifreyi kaldır
    user_data = {k: v for k, v in user.items() if k != "hashed_password"}
    return user_data


@app.get("/api/auth/check")
async def check_auth(user: dict = Depends(get_current_user_optional)):
    """Auth durumu kontrolü (guest dahil)"""
    if user:
        return {
            "authenticated": True,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "credit_balance": user["credit_balance"],
                "subscription_tier": user["subscription_tier"],
                "role": user["role"]
            }
        }
    return {"authenticated": False, "user": None}


class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@app.post("/api/auth/forgot-password")
async def forgot_password(data: ForgotPasswordRequest):
    """Şifre sıfırlama token'ı oluştur"""
    import secrets
    from datetime import datetime, timedelta
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # Kullanıcıyı bul
        cursor.execute("SELECT id, email, username FROM users WHERE email = ?", (data.email,))
        user = cursor.fetchone()
        
        if not user:
            # Güvenlik: Email bulunamasa bile başarılı mesajı dön
            return {"message": "Eğer e-posta kayıtlıysa, şifre sıfırlama linki gönderildi."}
        
        # Token oluştur
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(hours=1)  # 1 saat geçerli
        
        # Token'ı kaydet
        cursor.execute(
            """INSERT INTO password_reset_tokens (user_id, token, expires_at)
               VALUES (?, ?, ?)""",
            (user["id"], token, expires_at.isoformat())
        )
        conn.commit()
        
        # Gerçek uygulamada burada email gönderilir
        # Şimdilik token'ı response'da dönelim (TEST için)
        return {
            "message": "Eğer e-posta kayıtlıysa, şifre sıfırlama linki gönderildi.",
            "token": token  # PROD'da bu kaldırılacak, sadece TEST için
        }
        
    finally:
        conn.close()


@app.post("/api/auth/reset-password")
async def reset_password(data: ResetPasswordRequest):
    """Token ile şifre sıfırla"""
    from datetime import datetime
    from src.auth import get_password_hash
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # Token'ı kontrol et
        cursor.execute(
            """SELECT prt.id, prt.user_id, prt.expires_at, prt.used
               FROM password_reset_tokens prt
               WHERE prt.token = ?""",
            (data.token,)
        )
        token_data = cursor.fetchone()
        
        if not token_data:
            raise HTTPException(400, "Geçersiz token")
        
        token_id = token_data["id"]
        user_id = token_data["user_id"]
        expires_at = datetime.fromisoformat(token_data["expires_at"])
        used = token_data["used"]
        
        # Token kullanılmış mı?
        if used:
            raise HTTPException(400, "Bu token zaten kullanıldı")
        
        # Token süresi dolmuş mu?
        if datetime.now() > expires_at:
            raise HTTPException(400, "Token süresi dolmuş")
        
        # Şifreyi hashle ve güncelle
        hashed_password = get_password_hash(data.new_password)
        cursor.execute(
            "UPDATE users SET hashed_password = ? WHERE id = ?",
            (hashed_password, user_id)
        )
        
        # Token'ı kullanılmış olarak işaretle
        cursor.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE id = ?",
            (token_id,)
        )
        
        conn.commit()
        
        return {"message": "Şifreniz başarıyla güncellendi"}
        
    finally:
        conn.close()


# =============================================================================
# PAYMENT API - Ödeme İşlemleri
# =============================================================================

@app.get("/api/pricing")
async def get_pricing():
    """Fiyatlandırma bilgilerini getir"""
    return credit_manager.get_pricing()


@app.post("/api/payment/create")
async def create_payment(
    data: PaymentCreate,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """PayTR ödeme başlat"""
    result = paytr_client.create_payment_token(
        user_id=user["id"],
        user_email=user["email"],
        package_type=data.package,
        user_ip=get_client_ip(request),
        user_name=user.get("username", "KatalogBul Kullanıcı")
    )
    
    if result["status"] == "success":
        return {
            "iframe_token": result["token"],
            "merchant_oid": result["merchant_oid"]
        }
    else:
        raise HTTPException(400, result.get("error", "Ödeme başlatılamadı"))


@app.post("/api/payment/callback")
async def payment_callback(request: Request):
    """PayTR bildirim URL - ödeme sonucu"""
    try:
        form_data = await request.form()
        post_data = dict(form_data)
        
        result = paytr_client.process_callback(post_data)
        
        if result["success"]:
            return "OK"
        else:
            print(f"Payment callback error: {result['message']}")
            return "OK"  # PayTR'a her zaman OK dönmeli
            
    except Exception as e:
        print(f"Payment callback exception: {e}")
        return "OK"


@app.get("/api/payment/history")
async def get_payment_history(user: dict = Depends(get_current_user)):
    """Kullanıcının ödeme geçmişi"""
    return paytr_client.get_user_payments(user["id"])


# Ödeme sonuç sayfaları
@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success():
    return """
    <!DOCTYPE html>
    <html><head><title>Ödeme Başarılı</title>
    <script>
        setTimeout(function() {
            window.parent.postMessage({type: 'payment_success'}, '*');
            window.location.href = '/';
        }, 2000);
    </script>
    </head><body style="font-family:sans-serif;text-align:center;padding:50px;">
    <h1 style="color:#10B981;">✓ Ödeme Başarılı!</h1>
    <p>Krediniz hesabınıza eklendi. Yönlendiriliyorsunuz...</p>
    </body></html>
    """


@app.get("/payment/fail", response_class=HTMLResponse)
async def payment_fail():
    return """
    <!DOCTYPE html>
    <html><head><title>Ödeme Başarısız</title>
    <script>
        setTimeout(function() {
            window.parent.postMessage({type: 'payment_failed'}, '*');
            window.location.href = '/';
        }, 3000);
    </script>
    </head><body style="font-family:sans-serif;text-align:center;padding:50px;">
    <h1 style="color:#EF4444;">✗ Ödeme Başarısız</h1>
    <p>Ödeme işlemi tamamlanamadı. Yönlendiriliyorsunuz...</p>
    </body></html>
    """


# =============================================================================
# FAVORITES API - Favori PDF'ler
# =============================================================================

class AddFavoriteRequest(BaseModel):
    pdf_url: str
    title: str
    snippet: Optional[str] = None
    file_size: Optional[str] = None


@app.post("/api/favorites/add")
async def add_favorite(data: AddFavoriteRequest, user: dict = Depends(get_current_user)):
    """Favorilere ekle"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            """INSERT OR IGNORE INTO favorites (user_id, pdf_url, title, snippet, file_size)
               VALUES (?, ?, ?, ?, ?)""",
            (user["id"], data.pdf_url, data.title, data.snippet, data.file_size)
        )
        conn.commit()
        
        if cursor.rowcount > 0:
            return {"message": "Favorilere eklendi"}
        else:
            return {"message": "Zaten favorilerde"}
            
    finally:
        conn.close()


@app.delete("/api/favorites/remove")
async def remove_favorite(pdf_url: str, user: dict = Depends(get_current_user)):
    """Favorilerden çıkar"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "DELETE FROM favorites WHERE user_id = ? AND pdf_url = ?",
            (user["id"], pdf_url)
        )
        conn.commit()
        
        if cursor.rowcount > 0:
            return {"message": "Favorilerden kaldırıldı"}
        else:
            raise HTTPException(404, "Favori bulunamadı")
            
    finally:
        conn.close()


@app.get("/api/favorites/list")
async def list_favorites(
    page: int = 1,
    per_page: int = 20,
    user: dict = Depends(get_current_user)
):
    """Favorileri listele"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        offset = (page - 1) * per_page
        
        cursor.execute(
            """SELECT COUNT(*) FROM favorites WHERE user_id = ?""",
            (user["id"],)
        )
        total = cursor.fetchone()[0]
        
        cursor.execute(
            """SELECT * FROM favorites WHERE user_id = ? 
               ORDER BY added_at DESC LIMIT ? OFFSET ?""",
            (user["id"], per_page, offset)
        )
        
        favorites = [dict(row) for row in cursor.fetchall()]
        
        return {
            "favorites": favorites,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page
        }
        
    finally:
        conn.close()


@app.get("/api/favorites/check")
async def check_favorite(pdf_url: str, user: dict = Depends(get_current_user)):
    """Favoride mi kontrol et"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM favorites WHERE user_id = ? AND pdf_url = ?",
            (user["id"], pdf_url)
        )
        count = cursor.fetchone()[0]
        
        return {"is_favorite": count > 0}
        
    finally:
        conn.close()


# =============================================================================
# SEARCH LOGS API - Arama Geçmişi
# =============================================================================

@app.get("/api/search-logs")
async def get_search_logs(
    page: int = 1,
    per_page: int = 20,
    user: dict = Depends(get_current_user)
):
    """Kullanıcının arama geçmişi"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        offset = (page - 1) * per_page
        
        cursor.execute(
            """SELECT COUNT(*) FROM search_logs WHERE user_id = ?""",
            (user["id"],)
        )
        total = cursor.fetchone()[0]
        
        cursor.execute(
            """SELECT * FROM search_logs WHERE user_id = ? 
               ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (user["id"], per_page, offset)
        )
        
        logs = [dict(row) for row in cursor.fetchall()]
        
        # Engines JSON'u parse et
        for log in logs:
            if log.get("engines_used"):
                try:
                    log["engines_used"] = json.loads(log["engines_used"])
                except:
                    log["engines_used"] = []
        
        return {
            "logs": logs,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page
        }
        
    finally:
        conn.close()


# =============================================================================
# SAVED SEARCHES API - Kayıtlı Aramalar
# =============================================================================

@app.get("/api/saved-searches")
async def get_saved_searches(
    brand: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "recent",
    page: int = 1,
    per_page: int = 50
):
    """
    Tüm kayıtlı aramaları listele (marka ve kategori bazında gruplandırılmış)
    
    Query params:
        brand: Marka filtresi
        category: Kategori filtresi
        search: Arama metni (query içinde)
        sort: Sıralama (recent, popular, brand)
        page: Sayfa numarası
        per_page: Sayfa başına sonuç
    """
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # WHERE koşulları
        where_conditions = []
        params = []
        
        if brand:
            where_conditions.append("query LIKE ?")
            params.append(f"%{brand}%")
        
        if category:
            # Category mapping
            mapped_category = map_doc_type_to_category(category)
            where_conditions.append("doc_type = ?")
            params.append(mapped_category)
        
        if search:
            where_conditions.append("query LIKE ?")
            params.append(f"%{search}%")
        
        where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        
        # Sıralama
        order_by = {
            "recent": "created_at DESC",
            "popular": "search_count DESC",
            "brand": "brand ASC, created_at DESC"
        }.get(sort, "created_at DESC")
        
        # Toplam sayı
        count_query = f"""
            SELECT COUNT(DISTINCT query) 
            FROM search_logs 
            {where_clause}
        """
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]
        
        # Marka ve kategori çıkarma ile gruplandırılmış sorgu
        # Her unique query için marka ve kategori çıkar
        offset = (page - 1) * per_page
        
        # Önce tüm kayıtları al, sonra Python'da işle
        query_sql = f"""
            SELECT 
                id,
                query,
                doc_type,
                result_count,
                created_at,
                user_id,
                engines_used
            FROM search_logs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        
        cursor.execute(query_sql, params + [per_page, offset])
        rows = cursor.fetchall()
        
        # Marka ve kategori çıkar, gruplandır
        searches = []
        seen_queries = {}  # Aynı query'yi tekrar gösterme
        
        for row in rows:
            row_dict = dict(row)
            query = row_dict.get("query", "")
            
            # Aynı query'yi atla (en yenisini tut)
            if query in seen_queries:
                continue
            seen_queries[query] = True
            
            # Marka çıkar
            brand_extracted = extract_brand_from_query(query)
            
            # Kategori çıkar
            doc_type = row_dict.get("doc_type")
            category_extracted = map_doc_type_to_category(doc_type)
            category_label = get_category_label(category_extracted)
            
            # Aynı query'nin kaç kez arandığını say
            cursor.execute(
                "SELECT COUNT(*) FROM search_logs WHERE query = ?",
                (query,)
            )
            search_count = cursor.fetchone()[0]
            
            searches.append({
                "id": row_dict.get("id"),
                "query": query,
                "brand": brand_extracted,
                "category": category_extracted,
                "category_label": category_label,
                "result_count": row_dict.get("result_count", 0),
                "created_at": row_dict.get("created_at"),
                "user_id": row_dict.get("user_id"),
                "search_count": search_count,
                "engines_used": json.loads(row_dict.get("engines_used", "[]")) if row_dict.get("engines_used") else []
            })
        
        # Sıralama uygula
        if sort == "popular":
            searches.sort(key=lambda x: x["search_count"], reverse=True)
        elif sort == "brand":
            searches.sort(key=lambda x: (x["brand"] or "", x["created_at"] or ""), reverse=True)
        # recent zaten DESC sıralı
        
        # Marka ve kategori listelerini oluştur
        all_brands = set()
        all_categories = set()
        brand_counts = {}
        category_counts = {}
        
        cursor.execute(f"SELECT query, doc_type FROM search_logs {where_clause}", params)
        all_rows = cursor.fetchall()
        
        for row in all_rows:
            query = row[0]
            doc_type = row[1]
            
            brand = extract_brand_from_query(query)
            if brand:
                all_brands.add(brand)
                brand_counts[brand] = brand_counts.get(brand, 0) + 1
            
            category = map_doc_type_to_category(doc_type)
            all_categories.add(category)
            category_counts[category] = category_counts.get(category, 0) + 1
        
        return {
            "searches": searches,
            "brands": sorted(list(all_brands)),
            "categories": sorted(list(all_categories)),
            "stats": {
                "total": total,
                "by_brand": brand_counts,
                "by_category": category_counts
            },
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": (total + per_page - 1) // per_page
            }
        }
        
    finally:
        conn.close()


@app.get("/api/saved-searches/stats")
async def get_saved_searches_stats():
    """Kayıtlı aramalar istatistikleri"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # Toplam arama sayısı
        cursor.execute("SELECT COUNT(*) FROM search_logs")
        total_searches = cursor.fetchone()[0]
        
        # Unique markalar
        cursor.execute("SELECT DISTINCT query FROM search_logs")
        all_queries = [row[0] for row in cursor.fetchall()]
        
        unique_brands = set()
        brand_counts = {}
        
        for query in all_queries:
            brand = extract_brand_from_query(query)
            if brand:
                unique_brands.add(brand)
                brand_counts[brand] = brand_counts.get(brand, 0) + 1
        
        # Unique kategoriler
        cursor.execute("SELECT DISTINCT doc_type FROM search_logs WHERE doc_type IS NOT NULL")
        all_doc_types = [row[0] for row in cursor.fetchall()]
        
        unique_categories = set()
        category_counts = {}
        
        for doc_type in all_doc_types:
            category = map_doc_type_to_category(doc_type)
            unique_categories.add(category)
            category_counts[category] = category_counts.get(category, 0) + 1
        
        # En çok aranan markalar (top 10)
        most_searched_brands = sorted(
            brand_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        # En çok aranan kategoriler
        most_searched_categories = sorted(
            category_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Son 10 arama
        cursor.execute("""
            SELECT query, created_at, result_count
            FROM search_logs
            ORDER BY created_at DESC
            LIMIT 10
        """)
        recent_searches = [
            {
                "query": row[0],
                "created_at": row[1],
                "result_count": row[2]
            }
            for row in cursor.fetchall()
        ]
        
        return {
            "total_searches": total_searches,
            "unique_brands": len(unique_brands),
            "unique_categories": len(unique_categories),
            "most_searched_brands": [
                {"brand": brand, "count": count}
                for brand, count in most_searched_brands
            ],
            "most_searched_categories": [
                {"category": category, "label": get_category_label(category), "count": count}
                for category, count in most_searched_categories
            ],
            "recent_searches": recent_searches
        }
        
    finally:
        conn.close()


# =============================================================================
# ADMIN API - Yönetim Paneli
# =============================================================================

@app.get("/api/admin/dashboard")
async def admin_dashboard(admin: dict = Depends(get_admin_user)):
    """Admin dashboard istatistikleri"""
    import sqlite3
    from datetime import datetime
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    today = datetime.now().date().isoformat()
    
    # Toplam kullanıcı
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    # Aktif abonelikler
    cursor.execute("SELECT COUNT(*) FROM users WHERE subscription_tier != 'free'")
    active_subs = cursor.fetchone()[0]
    
    # Bugünkü aramalar
    cursor.execute("SELECT COUNT(*) FROM search_logs WHERE DATE(created_at) = ?", (today,))
    today_searches = cursor.fetchone()[0]
    
    # Bugünkü gelir
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) FROM payments 
        WHERE DATE(created_at) = ? AND status = 'success'
    """, (today,))
    today_revenue = cursor.fetchone()[0]
    
    # Cache kayıtları
    cursor.execute("SELECT COUNT(*) FROM search_cache")
    cache_entries = cursor.fetchone()[0]
    
    # Tier dağılımı
    cursor.execute("""
        SELECT subscription_tier, COUNT(*) FROM users 
        GROUP BY subscription_tier
    """)
    tier_distribution = dict(cursor.fetchall())
    
    conn.close()
    
    return {
        "total_users": total_users,
        "active_subscriptions": active_subs,
        "today_searches": today_searches,
        "today_revenue": today_revenue,
        "cache_entries": cache_entries,
        "tier_distribution": tier_distribution
    }


@app.get("/api/admin/users")
async def admin_list_users(
    page: int = 1,
    per_page: int = 20,
    tier: Optional[str] = None,
    admin: dict = Depends(get_admin_user)
):
    """Kullanıcı listesi"""
    return user_manager.list_users(page=page, per_page=per_page, tier=tier)


@app.get("/api/admin/users/{user_id}")
async def admin_get_user(user_id: int, admin: dict = Depends(get_admin_user)):
    """Kullanıcı detayı"""
    user = user_manager.get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    
    user.pop("hashed_password", None)
    return user


@app.put("/api/admin/users/{user_id}")
async def admin_update_user(
    user_id: int,
    updates: dict,
    admin: dict = Depends(get_admin_user)
):
    """Kullanıcı güncelle"""
    success = user_manager.update_user(user_id, **updates)
    if not success:
        raise HTTPException(400, "Güncelleme başarısız")
    return {"message": "Kullanıcı güncellendi"}


@app.post("/api/admin/users/{user_id}/credits")
async def admin_adjust_credits(
    user_id: int,
    amount: int,
    reason: str = "",
    admin: dict = Depends(get_admin_user)
):
    """Kredi ekle/çıkar"""
    if amount > 0:
        success = credit_manager.add_credits(user_id, amount, reason)
    else:
        success = credit_manager.deduct_credits(user_id, abs(amount), reason)
    
    if not success:
        raise HTTPException(400, "Kredi işlemi başarısız")
    
    new_balance = credit_manager.get_balance(user_id)
    return {"message": "Kredi güncellendi", "new_balance": new_balance}


# Settings API
@app.get("/api/admin/settings")
async def admin_get_settings(
    category: Optional[str] = None,
    admin: dict = Depends(get_admin_user)
):
    """Tüm ayarları getir"""
    return settings_manager.get_all(category=category, masked=True)


@app.get("/api/admin/settings/{key}")
async def admin_get_setting(key: str, admin: dict = Depends(get_admin_user)):
    """Tek ayar getir (şifre çözülmüş)"""
    value = settings_manager.get(key)
    return {"key": key, "value": value}


@app.put("/api/admin/settings/{key}")
async def admin_update_setting(
    key: str,
    value: str,
    admin: dict = Depends(get_admin_user)
):
    """Ayar güncelle"""
    success = settings_manager.set(key, value, admin_id=admin["id"])
    if not success:
        raise HTTPException(400, "Ayar güncellenemedi")
    return {"message": "Ayar güncellendi"}


# Payments API
@app.get("/api/admin/payments")
async def admin_list_payments(
    page: int = 1,
    per_page: int = 20,
    status: Optional[str] = None,
    admin: dict = Depends(get_admin_user)
):
    """Ödeme listesi"""
    import sqlite3
    
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Count
    count_query = "SELECT COUNT(*) FROM payments WHERE 1=1"
    list_query = """
        SELECT p.*, u.email, u.username 
        FROM payments p 
        LEFT JOIN users u ON p.user_id = u.id 
        WHERE 1=1
    """
    params = []
    
    if status:
        count_query += " AND status = ?"
        list_query += " AND p.status = ?"
        params.append(status)
    
    cursor.execute(count_query, params)
    total = cursor.fetchone()[0]
    
    list_query += " ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])
    
    cursor.execute(list_query, params)
    payments = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        "items": payments,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page
    }


# Search Logs API
@app.get("/api/admin/search-logs")
async def admin_list_search_logs(
    page: int = 1,
    per_page: int = 50,
    user_id: Optional[int] = None,
    admin: dict = Depends(get_admin_user)
):
    """Arama logları"""
    import sqlite3
    
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    count_query = "SELECT COUNT(*) FROM search_logs WHERE 1=1"
    list_query = """
        SELECT sl.*, u.email, u.username 
        FROM search_logs sl 
        LEFT JOIN users u ON sl.user_id = u.id 
        WHERE 1=1
    """
    params = []
    
    if user_id:
        count_query += " AND user_id = ?"
        list_query += " AND sl.user_id = ?"
        params.append(user_id)
    
    cursor.execute(count_query, params)
    total = cursor.fetchone()[0]
    
    list_query += " ORDER BY sl.created_at DESC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])
    
    cursor.execute(list_query, params)
    logs = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        "items": logs,
        "total": total,
        "page": page,
        "per_page": per_page
    }


# Admin sayfası
@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """Admin panel sayfası"""
    return FileResponse("frontend/admin.html")


# =============================================================================
# KREDİ TALEPLERİ API
# =============================================================================

class CreditRequestCreate(BaseModel):
    package_type: str
    credit_amount: int
    price_amount: int

@app.post("/api/credit-requests")
async def create_credit_request(
    data: CreditRequestCreate,
    user: dict = Depends(get_current_user)
):
    """Yeni kredi talebi oluştur"""
    import sqlite3
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO credit_requests (user_id, package_type, credit_amount, price_amount)
            VALUES (?, ?, ?, ?)
        """, (user["id"], data.package_type, data.credit_amount, data.price_amount))
        
        request_id = cursor.lastrowid
        conn.commit()
        
        return {"message": "Kredi talebiniz alındı. Admin onayı bekleniyor.", "request_id": request_id}
    except Exception as e:
        raise HTTPException(500, f"Talep oluşturulamadı: {str(e)}")
    finally:
        conn.close()


@app.get("/api/credit-requests/my")
async def my_credit_requests(user: dict = Depends(get_current_user)):
    """Kullanıcının kendi kredi taleplerini listele"""
    import sqlite3
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM credit_requests 
        WHERE user_id = ? 
        ORDER BY created_at DESC
    """, (user["id"],))
    
    requests = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return {"requests": requests}


@app.get("/api/admin/credit-requests")
async def admin_list_credit_requests(
    status: Optional[str] = None,
    admin: dict = Depends(get_admin_user)
):
    """Admin: Tüm kredi taleplerini listele"""
    import sqlite3
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if status:
        cursor.execute("""
            SELECT cr.*, u.username, u.email, u.phone, u.credit_balance
            FROM credit_requests cr
            JOIN users u ON cr.user_id = u.id
            WHERE cr.status = ?
            ORDER BY cr.created_at DESC
        """, (status,))
    else:
        cursor.execute("""
            SELECT cr.*, u.username, u.email, u.phone, u.credit_balance
            FROM credit_requests cr
            JOIN users u ON cr.user_id = u.id
            ORDER BY cr.created_at DESC
        """)
    
    requests = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return {"requests": requests}


class CreditRequestAction(BaseModel):
    action: str  # approve, reject
    admin_note: Optional[str] = None

@app.post("/api/admin/credit-requests/{request_id}")
async def admin_process_credit_request(
    request_id: int,
    data: CreditRequestAction,
    admin: dict = Depends(get_admin_user)
):
    """Admin: Kredi talebini onayla veya reddet"""
    import sqlite3
    from datetime import datetime
    
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Talebi al
        cursor.execute("SELECT * FROM credit_requests WHERE id = ?", (request_id,))
        request = cursor.fetchone()
        
        if not request:
            raise HTTPException(404, "Talep bulunamadı")
        
        if request["status"] != "pending":
            raise HTTPException(400, "Bu talep zaten işlenmiş")
        
        if data.action == "approve":
            # Kredi ekle
            cursor.execute("""
                UPDATE users SET credit_balance = credit_balance + ?
                WHERE id = ?
            """, (request["credit_amount"], request["user_id"]))
            
            # Talebi güncelle
            cursor.execute("""
                UPDATE credit_requests 
                SET status = 'approved', admin_note = ?, processed_by = ?, processed_at = ?
                WHERE id = ?
            """, (data.admin_note, admin["id"], datetime.now().isoformat(), request_id))
            
            conn.commit()
            return {"message": f"{request['credit_amount']} kredi başarıyla eklendi"}
            
        elif data.action == "reject":
            cursor.execute("""
                UPDATE credit_requests 
                SET status = 'rejected', admin_note = ?, processed_by = ?, processed_at = ?
                WHERE id = ?
            """, (data.admin_note, admin["id"], datetime.now().isoformat(), request_id))
            
            conn.commit()
            return {"message": "Talep reddedildi"}
        else:
            raise HTTPException(400, "Geçersiz aksiyon")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"İşlem hatası: {str(e)}")
    finally:
        conn.close()


# Legal sayfaları
@app.get("/legal/{page}", response_class=HTMLResponse)
async def legal_page(page: str):
    """Yasal belgeler"""
    valid_pages = ["mesafeli_satis_sozlesmesi", "iptal_iade_kosullari", 
                   "kullanim_kosullari", "gizlilik_politikasi"]
    
    if page not in valid_pages:
        raise HTTPException(404, "Sayfa bulunamadı")
    
    return FileResponse(f"frontend/legal/{page}.html")


# =============================================================================
# KATALOG ÖĞRENME SİSTEMİ API
# =============================================================================

from fastapi import UploadFile, File
from sse_starlette.sse import EventSourceResponse
from src.catalog_service import get_catalog_service, CatalogService

catalog_service = get_catalog_service()


@app.get("/catalogs", response_class=HTMLResponse)
async def catalogs_page():
    """Katalog yönetim sayfası"""
    return FileResponse("frontend/catalog-viewer.html")


@app.post("/api/catalogs/upload")
async def upload_catalog(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user)
):
    """
    PDF katalog yükle ve analizi başlat
    
    1. Dosyayı kaydet
    2. Kredi kontrolü yap
    3. Arka planda analizi başlat
    """
    # PDF kontrolü
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, "Sadece PDF dosyaları yüklenebilir")
    
    # Dosya boyutu kontrolü (max 100MB)
    file_bytes = await file.read()
    if len(file_bytes) > 100 * 1024 * 1024:
        raise HTTPException(400, "Dosya boyutu 100MB'ı aşamaz")
    
    # Kredi kontrolü
    credit_check = catalog_service.check_analysis_credits(user["id"])
    if not credit_check["allowed"]:
        raise HTTPException(402, credit_check.get("reason", "Yetersiz kredi"))
    
    # Dosyayı kaydet
    result = catalog_service.upload_catalog(
        user_id=user["id"],
        file_bytes=file_bytes,
        original_name=file.filename
    )
    
    # Krediyi düş
    if credit_check["credits_needed"] > 0:
        catalog_service.deduct_analysis_credits(user["id"])
    
    # Arka planda analizi başlat
    background_tasks.add_task(run_catalog_analysis, result["id"])
    
    return {
        "success": True,
        "catalog_id": result["id"],
        "filename": result["original_name"],
        "total_pages": result["total_pages"],
        "status": "pending",
        "message": "Katalog yüklendi, analiz başlatılıyor..."
    }


async def run_catalog_analysis(catalog_id: int):
    """Arka planda katalog analizi çalıştır"""
    try:
        await catalog_service.analyze_catalog(catalog_id)
    except Exception as e:
        import logging
        logging.error(f"Katalog analiz hatası: {e}")
        catalog_service.update_progress(catalog_id, 0, str(e), "failed")


@app.get("/api/catalogs")
async def list_user_catalogs(
    page: int = 1,
    per_page: int = 20,
    user: dict = Depends(get_current_user)
):
    """Kullanıcının kataloglarını listele"""
    return catalog_service.get_user_catalogs(user["id"], page, per_page)


@app.get("/api/catalogs/{catalog_id}")
async def get_catalog_detail(
    catalog_id: int,
    user: dict = Depends(get_current_user)
):
    """Katalog detayını al"""
    catalog = catalog_service.get_catalog_by_id(catalog_id, user["id"])
    if not catalog:
        raise HTTPException(404, "Katalog bulunamadı")
    return catalog


@app.get("/api/catalogs/{catalog_id}/progress")
async def get_catalog_progress_sse(
    catalog_id: int,
    request: Request,
    user: dict = Depends(get_current_user_optional)
):
    """
    Katalog analiz ilerlemesini SSE ile stream et
    
    Event format:
    data: {"status": "analyzing", "progress": 45, "message": "Sayfa 15/30 işleniyor..."}
    """
    async def event_generator():
        last_progress = -1
        
        while True:
            # Bağlantı koptu mu kontrol et
            if await request.is_disconnected():
                break
            
            # İlerleme durumunu al
            progress = catalog_service.get_progress(catalog_id)
            
            if progress:
                # Değişiklik varsa gönder
                if progress["progress"] != last_progress or progress["status"] in ["completed", "failed"]:
                    last_progress = progress["progress"]
                    
                    yield {
                        "event": "progress",
                        "data": json.dumps(progress)
                    }
                    
                    # Tamamlandı veya hata varsa stream'i kapat
                    if progress["status"] in ["completed", "failed"]:
                        break
            
            await asyncio.sleep(1)
    
    return EventSourceResponse(event_generator())


@app.get("/api/catalogs/{catalog_id}/toc")
async def get_catalog_toc(
    catalog_id: int,
    user: dict = Depends(get_current_user_optional)
):
    """Katalog içindekiler listesini al"""
    toc = catalog_service.get_catalog_toc(catalog_id)
    return toc


@app.get("/api/catalogs/{catalog_id}/pages/{page_num}/image")
async def get_catalog_page_image(
    catalog_id: int,
    page_num: int,
    user: dict = Depends(get_current_user_optional)
):
    """Katalog sayfa görselini al"""
    try:
        image_bytes = catalog_service.get_page_image(catalog_id, page_num)
        return StreamingResponse(
            io.BytesIO(image_bytes),
            media_type="image/png"
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/catalogs/{catalog_id}/pages/{page_num}/parts")
async def get_catalog_page_parts(
    catalog_id: int,
    page_num: int,
    user: dict = Depends(get_current_user_optional)
):
    """Katalog sayfa parça tablosunu al"""
    parts = catalog_service.get_page_parts(catalog_id, page_num)
    return {"parts": parts}


# ================================================================
# KAYNAK TARAMA SİSTEMİ (Admin)
# ================================================================

from src.source_scanner import SourceScanner
from src.firecrawl_google_scraper import FirecrawlGoogleScraper

@app.get("/api/admin/sources")
async def get_sources(
    status: Optional[str] = None,
    user: dict = Depends(get_admin_user)
):
    """Tüm kaynakları getir (Admin)"""
    scanner = SourceScanner(db)
    
    if status:
        if status == "pending":
            sources = scanner.get_pending_sources(limit=100)
        elif status == "completed":
            sources = scanner.get_completed_sources(limit=100)
        else:
            all_sources = scanner.get_all_sources()
            sources = all_sources.get(status, [])
    else:
        sources = scanner.get_all_sources()
    
    return {"sources": sources}


@app.get("/api/admin/sources/stats")
async def get_source_stats(user: dict = Depends(get_admin_user)):
    """Kaynak tarama istatistikleri (Admin)"""
    scanner = SourceScanner(db)
    stats = scanner.get_statistics()
    return stats


@app.post("/api/admin/sources/{source_id}/scan")
async def scan_source(
    source_id: int,
    user: dict = Depends(get_admin_user)
):
    """Tek bir kaynağı tara (Admin)"""
    serper_key = settings_manager.get("serper_api_key") or os.getenv("SERPER_API_KEY")
    
    if not serper_key:
        raise HTTPException(400, "Serper API key yapılandırılmamış")
    
    scanner = SourceScanner(db, serper_key)
    result = await scanner.scan_source(source_id)
    await scanner.close()
    
    return result


@app.post("/api/admin/sources/scan-multiple")
async def scan_multiple_sources(
    source_ids: List[int],
    user: dict = Depends(get_admin_user)
):
    """Birden fazla kaynağı tara (Admin)"""
    serper_key = settings_manager.get("serper_api_key") or os.getenv("SERPER_API_KEY")
    
    if not serper_key:
        raise HTTPException(400, "Serper API key yapılandırılmamış")
    
    scanner = SourceScanner(db, serper_key)
    result = await scanner.scan_multiple_sources(source_ids)
    
    return result


@app.post("/api/admin/sources/scan-all-pending")
async def scan_all_pending(user: dict = Depends(get_admin_user)):
    """Tüm bekleyen kaynakları tara (Admin)"""
    serper_key = settings_manager.get("serper_api_key") or os.getenv("SERPER_API_KEY")
    
    if not serper_key:
        raise HTTPException(400, "Serper API key yapılandırılmamış")
    
    scanner = SourceScanner(db, serper_key)
    pending = scanner.get_pending_sources(limit=50)
    
    if not pending:
        return {"message": "Bekleyen kaynak yok", "scanned": 0}
    
    source_ids = [s["id"] for s in pending]
    result = await scanner.scan_multiple_sources(source_ids)
    
    return result


@app.get("/api/admin/sources/{source_id}/pdfs")
async def get_source_pdfs(
    source_id: int,
    user: dict = Depends(get_admin_user)
):
    """Bir kaynaktan bulunan PDF'leri getir (Admin)"""
    scanner = SourceScanner(db)
    pdfs = scanner.get_scanned_pdfs(source_id)
    return {"pdfs": pdfs, "total": len(pdfs)}


@app.delete("/api/admin/sources/{source_id}")
async def delete_source(
    source_id: int,
    user: dict = Depends(get_admin_user)
):
    """Kaynağı sil (Admin)"""
    scanner = SourceScanner(db)
    success = scanner.delete_source(source_id)
    return {"success": success}


@app.post("/api/admin/sources/{source_id}/reset")
async def reset_source(
    source_id: int,
    user: dict = Depends(get_admin_user)
):
    """Kaynağı pending'e döndür (Admin)"""
    scanner = SourceScanner(db)
    success = scanner.reset_source(source_id)
    return {"success": success}


# ================================================================
# KAYITLI LİNKLER (Discovered PDFs - Admin)
# ================================================================

@app.get("/api/admin/discovered-pdfs")
async def get_discovered_pdfs(
    page: int = Query(1, ge=1, description="Sayfa numarası"),
    per_page: int = Query(50, ge=10, le=200, description="Sayfa başına sonuç"),
    domain: Optional[str] = Query(None, description="Domain filtresi"),
    brand: Optional[str] = Query(None, description="Marka filtresi"),
    min_size: Optional[float] = Query(None, description="Minimum boyut (MB)"),
    max_size: Optional[float] = Query(None, description="Maksimum boyut (MB)"),
    sort_by: str = Query("size_mb", description="Sıralama: size_mb, title, discovered_at"),
    sort_order: str = Query("desc", description="Sıralama yönü: asc, desc"),
    user: dict = Depends(get_admin_user)
):
    """Keşfedilen PDF'leri listele - Sayfalama, filtreleme ve sıralama (Admin)"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # Filtre koşulları
        conditions = ["is_valid = 1"]
        params = []
        
        if domain:
            conditions.append("domain LIKE ?")
            params.append(f"%{domain}%")
        
        if brand:
            conditions.append("brand LIKE ?")
            params.append(f"%{brand}%")
        
        if min_size is not None:
            conditions.append("size_mb >= ?")
            params.append(min_size)
        
        if max_size is not None:
            conditions.append("size_mb <= ?")
            params.append(max_size)
        
        where_clause = " AND ".join(conditions)
        
        # Sıralama validasyonu
        valid_sort_columns = ["size_mb", "title", "discovered_at", "domain"]
        if sort_by not in valid_sort_columns:
            sort_by = "size_mb"
        sort_direction = "DESC" if sort_order.lower() == "desc" else "ASC"
        
        # Toplam sayı
        cursor.execute(f"SELECT COUNT(*) FROM discovered_pdfs WHERE {where_clause}", params)
        total = cursor.fetchone()[0]
        
        # Sayfalama
        offset = (page - 1) * per_page
        total_pages = (total + per_page - 1) // per_page if total > 0 else 1
        
        # Sonuçları çek
        cursor.execute(f"""
            SELECT id, url, title, domain, size_bytes, size_mb, brand, model, 
                   category, discovered_at, last_checked
            FROM discovered_pdfs 
            WHERE {where_clause}
            ORDER BY {sort_by} {sort_direction} NULLS LAST
            LIMIT ? OFFSET ?
        """, params + [per_page, offset])
        
        pdfs = []
        for row in cursor.fetchall():
            pdfs.append({
                "id": row[0],
                "url": row[1],
                "title": row[2],
                "domain": row[3],
                "size_bytes": row[4],
                "size_mb": row[5],
                "size_formatted": f"{row[5]:.1f} MB" if row[5] else None,
                "brand": row[6],
                "model": row[7],
                "category": row[8],
                "discovered_at": row[9],
                "last_checked": row[10]
            })
        
        # Benzersiz domain ve brand listesi (filtreleme için)
        cursor.execute("SELECT DISTINCT domain FROM discovered_pdfs WHERE is_valid = 1 ORDER BY domain")
        domains = [r[0] for r in cursor.fetchall() if r[0]]
        
        cursor.execute("SELECT DISTINCT brand FROM discovered_pdfs WHERE is_valid = 1 AND brand IS NOT NULL ORDER BY brand")
        brands = [r[0] for r in cursor.fetchall() if r[0]]
        
        return {
            "items": pdfs,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "filters": {
                "domains": domains,
                "brands": brands
            }
        }
    finally:
        conn.close()


@app.delete("/api/admin/discovered-pdfs/{pdf_id}")
async def delete_discovered_pdf(
    pdf_id: int,
    user: dict = Depends(get_admin_user)
):
    """Keşfedilen PDF'i sil (Admin)"""
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM discovered_pdfs WHERE id = ?", (pdf_id,))
        conn.commit()
        return {"success": cursor.rowcount > 0}
    finally:
        conn.close()


# ================================================================
# PREMIUM ARAMA (Firecrawl + Google Scrape)
# ================================================================

@app.get("/api/search/premium")
async def search_premium_sites(
    q: str = Query(..., description="Arama sorgusu"),
    user: dict = Depends(get_current_user_optional)
):
    """Premium sitelerde arama yap (Scribd, Issuu, vb.)"""
    firecrawl_key = settings_manager.get("firecrawl_api_key") or os.getenv("FIRECRAWL_API_KEY")
    
    if not firecrawl_key:
        return {"results": [], "stats": {"error": "Firecrawl API key yapılandırılmamış"}}
    
    scraper = FirecrawlGoogleScraper(firecrawl_key, db)
    result = await scraper.search_premium_sites(q)
    await scraper.close()
    
    # Kaynak tarama için URL'leri işle (arka planda)
    if result.get("results"):
        scanner = SourceScanner(db)
        scanner.process_search_results(result["results"], q)
    
    return result


# ================================================================
# KAYNAK KEŞİF (Source Discovery - Firecrawl /map)
# ================================================================

from src.source_discovery import SourceDiscovery, SourceDomain
from sse_starlette.sse import EventSourceResponse
import json

# Global source discovery instance
_source_discovery: Optional[SourceDiscovery] = None

def get_source_discovery() -> SourceDiscovery:
    global _source_discovery
    if _source_discovery is None:
        firecrawl_key = settings_manager.get("firecrawl_api_key") or os.getenv("FIRECRAWL_API_KEY")
        _source_discovery = SourceDiscovery(firecrawl_key, db)
    return _source_discovery


@app.post("/api/sources/extract")
async def extract_sources_from_results(
    results: List[dict] = Body(..., description="Arama sonuçları")
):
    """
    Arama sonuçlarından benzersiz kaynakları (domain) çıkar
    
    Frontend arama yaptıktan sonra sonuçları buraya gönderir,
    benzersiz domain listesi döner.
    """
    discovery = get_source_discovery()
    domains = discovery.extract_domains_from_results(results)
    
    return {
        "sources": [d.to_dict() for d in domains],
        "total": len(domains)
    }


@app.get("/api/sources/{domain}/scan")
async def scan_source_sse(
    domain: str,
    paths: str = Query("", description="Virgülle ayrılmış path'ler")
):
    """
    Tek kaynağı tara - SSE stream
    
    Gerçek zamanlı progress ve bulunan PDF'leri stream eder.
    """
    discovery = get_source_discovery()
    
    path_list = [p.strip() for p in paths.split(",") if p.strip()] if paths else ["/"]
    source = SourceDomain(domain=domain, paths=path_list)
    
    async def event_generator():
        try:
            async for event in discovery.scan_domain_stream(source):
                yield {
                    "event": event["type"],
                    "data": json.dumps(event["data"], ensure_ascii=False)
                }
        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}, ensure_ascii=False)
            }
    
    return EventSourceResponse(event_generator())


@app.post("/api/sources/scan")
async def scan_source_sync(
    domain: str = Body(...),
    paths: List[str] = Body(default=[])
):
    """
    Tek kaynağı tara - Senkron (SSE desteklemeyen client'lar için)
    
    Tüm sonuçları bekleyip döner.
    """
    discovery = get_source_discovery()
    
    if not paths:
        paths = ["/"]
    
    source = SourceDomain(domain=domain, paths=paths)
    pdfs = await discovery.scan_domain(source)
    
    return {
        "source": source.to_dict(),
        "pdfs": [p.to_dict() for p in pdfs],
        "total": len(pdfs)
    }


@app.post("/api/sources/scan-multiple")
async def scan_multiple_sources(
    sources: List[dict] = Body(..., description="Kaynak listesi [{domain, paths}]")
):
    """
    Birden fazla kaynağı tara
    """
    discovery = get_source_discovery()
    all_results = []
    
    for source_data in sources:
        domain = source_data.get("domain", "")
        paths = source_data.get("paths", ["/"])
        
        if not domain:
            continue
        
        source = SourceDomain(domain=domain, paths=paths)
        pdfs = await discovery.scan_domain(source)
        
        all_results.append({
            "source": source.to_dict(),
            "pdfs": [p.to_dict() for p in pdfs],
            "count": len(pdfs)
        })
    
    total_pdfs = sum(r["count"] for r in all_results)
    
    return {
        "results": all_results,
        "total_sources": len(all_results),
        "total_pdfs": total_pdfs
    }


class SizeFilterRequest(BaseModel):
    """Boyut filtresi için request model"""
    pdfs: List[dict]
    min_mb: Optional[float] = None
    max_mb: Optional[float] = None


@app.post("/api/sources/filter-by-size")
async def filter_pdfs_by_size(request: SizeFilterRequest):
    """
    PDF listesini boyuta göre filtrele
    """
    filtered = []
    
    for pdf in request.pdfs:
        size_mb = pdf.get("size_mb")
        
        if size_mb is None:
            # Boyut bilinmiyorsa dahil et
            filtered.append(pdf)
            continue
        
        # Min kontrolü
        if request.min_mb is not None and size_mb < request.min_mb:
            continue
        
        # Max kontrolü
        if request.max_mb is not None and size_mb > request.max_mb:
            continue
        
        filtered.append(pdf)
    
    return {
        "pdfs": filtered,
        "total": len(filtered),
        "filtered_out": len(request.pdfs) - len(filtered)
    }

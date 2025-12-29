import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# =============================================================================
# API Keys - Veritabanından Okunur (Güvenli)
# =============================================================================
# API anahtarları artık veritabanında şifreli olarak saklanır
# Admin panelinden yönetilebilir: /admin -> API Ayarları
# 
# Fallback değerleri (veritabanı yoksa):
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")
SEARCHAPI_KEY = os.getenv("SEARCHAPI_KEY", "")

# =============================================================================
# Database Configuration
# =============================================================================
DATABASE_PATH = os.path.join("data", "pepc.db")

# Cache Configuration
CACHE_EXPIRY_DAYS = 3650  # Sonuçları 10 yıl sakla (pratik olarak sonsuza kadar)

# =============================================================================
# Thumbnail Configuration
# =============================================================================
THUMBNAIL_DIR = "thumbnails"

# =============================================================================
# Search Engines Configuration
# =============================================================================
SEARCH_ENGINES = {
    "serper": {
        "name": "Google (Serper)",
        "enabled": True,
        "priority": 1
    },
    "brave": {
        "name": "Brave Search",
        "enabled": True,
        "priority": 2
    },
    "yandex": {
        "name": "Yandex",
        "enabled": True,  # IAM token authentication aktif
        "priority": 3
    },
}


"""
Credit Manager - Kredi Yönetimi
Tier bazlı erişim kontrolü ve kredi hesaplama/düşme
"""
import sqlite3
from typing import Dict, List, Optional, Any
from datetime import datetime

from src.config import DATABASE_PATH
from src.settings_manager import get_settings_manager


# ================================================================
# TIER CONFIGURATION
# ================================================================

TIER_CONFIG = {
    "free": {
        "display_name": "Ücretsiz",
        "daily_search_limit": 5,
        "allowed_engines": [],  # Sadece cache
        "can_download": False,
        "source_scan": False,
    },
    "pro": {
        "display_name": "Pro",
        "daily_search_limit": None,  # Sınırsız (kredi bazlı)
        "allowed_engines": ["searchapi_google", "searchapi_bing", "brave"],
        "can_download": True,
        "source_scan": False,
    },
    "enterprise": {
        "display_name": "Enterprise",
        "daily_search_limit": None,
        "allowed_engines": ["searchapi_google", "searchapi_bing", "brave", 
                           "searchapi_baidu", "searchapi_naver", "yandex"],
        "can_download": True,
        "source_scan": True,
    }
}

# Motor -> Ayar key mapping
ENGINE_CREDIT_KEYS = {
    "searchapi_google": "api_credit_google",
    "searchapi_bing": "api_credit_bing",
    "brave": "api_credit_brave",
    "searchapi_baidu": "api_credit_baidu",
    "searchapi_naver": "api_credit_naver",
    "yandex": "api_credit_yandex",
    "serper": "api_credit_google",  # Serper = Google
}


class CreditManager:
    """Kredi yönetimi ve hesaplama"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DATABASE_PATH
        self.settings = get_settings_manager()
    
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_tier_config(self, tier: str) -> Dict[str, Any]:
        """Tier yapılandırmasını al"""
        return TIER_CONFIG.get(tier, TIER_CONFIG["free"])
    
    def get_allowed_engines(self, tier: str) -> List[str]:
        """Tier'a göre izin verilen motorları al"""
        config = self.get_tier_config(tier)
        return config.get("allowed_engines", [])
    
    def can_use_engine(self, tier: str, engine: str) -> bool:
        """Kullanıcı bu motoru kullanabilir mi?"""
        allowed = self.get_allowed_engines(tier)
        return engine in allowed
    
    def filter_engines(self, tier: str, requested_engines: List[str]) -> List[str]:
        """İstenilen motorları tier'a göre filtrele"""
        allowed = self.get_allowed_engines(tier)
        return [e for e in requested_engines if e in allowed]
    
    def get_engine_credit_cost(self, engine: str) -> int:
        """Motor başına kredi maliyetini al"""
        key = ENGINE_CREDIT_KEYS.get(engine, "api_credit_google")
        return self.settings.get_int(key, 10)
    
    def get_cache_credit_cost(self, tier: str) -> int:
        """Cache indirme kredi maliyetini al"""
        # Enterprise tier cache'i ücretsiz
        if tier == "enterprise":
            return 0
        
        key = f"cache_credit_{tier}"
        return self.settings.get_int(key, 1)
    
    def get_source_scan_credit_cost(self) -> int:
        """Kaynak tarama kredi maliyetini al"""
        return self.settings.get_int("source_scan_credit", 5)
    
    def calculate_search_cost(
        self,
        tier: str,
        engines: List[str],
        is_cached: bool
    ) -> int:
        """
        Arama maliyetini hesapla
        
        Args:
            tier: Kullanıcı tier'ı
            engines: Kullanılan motorlar
            is_cached: Cache'ten mi geldi
            
        Returns:
            Toplam kredi maliyeti
        """
        if is_cached:
            # Enterprise tier cache ücretsiz
            if tier == "enterprise":
                return 0
            return self.get_cache_credit_cost(tier)
        
        # API'den - her motor için ayrı maliyet
        total = 0
        allowed = self.get_allowed_engines(tier)
        
        for engine in engines:
            if engine in allowed:
                total += self.get_engine_credit_cost(engine)
        
        return total
    
    def calculate_download_cost(self, tier: str) -> int:
        """İndirme maliyetini hesapla"""
        return self.get_cache_credit_cost(tier)
    
    def check_credits(self, user_id: int, required: int) -> bool:
        """Yeterli kredi var mı?"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT credit_balance FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            
            if not row:
                return False
            
            return row["credit_balance"] >= required
        finally:
            conn.close()
    
    def deduct_credits(
        self,
        user_id: int,
        amount: int,
        reason: str = ""
    ) -> bool:
        """
        Kredi düş
        
        Args:
            user_id: Kullanıcı ID
            amount: Düşülecek miktar
            reason: İşlem sebebi
            
        Returns:
            Başarılı mı
        """
        if amount <= 0:
            return True
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE users 
                SET credit_balance = credit_balance - ?
                WHERE id = ? AND credit_balance >= ?
            """, (amount, user_id, amount))
            
            success = cursor.rowcount > 0
            conn.commit()
            
            return success
        finally:
            conn.close()
    
    def add_credits(
        self,
        user_id: int,
        amount: int,
        reason: str = ""
    ) -> bool:
        """Kredi ekle"""
        if amount <= 0:
            return False
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE users SET credit_balance = credit_balance + ?
                WHERE id = ?
            """, (amount, user_id))
            
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def get_balance(self, user_id: int) -> int:
        """Kredi bakiyesi al"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT credit_balance FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return row["credit_balance"] if row else 0
        finally:
            conn.close()
    
    def check_daily_limit(self, user_id: int, tier: str) -> bool:
        """
        Günlük limit kontrolü (Free tier için)
        
        Returns:
            True = limit aşılmadı, devam edebilir
        """
        config = self.get_tier_config(tier)
        limit = config.get("daily_search_limit")
        
        # Sınırsız
        if limit is None:
            return True
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            today = datetime.now().date().isoformat()
            
            cursor.execute("""
                SELECT daily_search_count, last_search_date 
                FROM users WHERE id = ?
            """, (user_id,))
            
            row = cursor.fetchone()
            if not row:
                return False
            
            # Farklı gün = sıfırdan başla
            if row["last_search_date"] != today:
                return True
            
            return row["daily_search_count"] < limit
        finally:
            conn.close()
    
    def can_download(self, tier: str) -> bool:
        """İndirme yetkisi var mı?"""
        config = self.get_tier_config(tier)
        return config.get("can_download", False)
    
    def can_source_scan(self, tier: str) -> bool:
        """Kaynak tarama yetkisi var mı?"""
        config = self.get_tier_config(tier)
        return config.get("source_scan", False)
    
    def log_search(
        self,
        user_id: Optional[int],
        query: str,
        doc_type: str,
        engines_used: List[str],
        result_count: int,
        credits_used: int,
        is_cached: bool,
        ip_address: str = None,
        user_agent: str = None
    ) -> int:
        """Arama logla"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            import json
            
            cursor.execute("""
                INSERT INTO search_logs 
                (user_id, query, doc_type, engines_used, result_count, 
                 credits_used, is_cached, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                query,
                doc_type,
                json.dumps(engines_used),
                result_count,
                credits_used,
                is_cached,
                ip_address,
                user_agent
            ))
            
            log_id = cursor.lastrowid
            conn.commit()
            return log_id
        finally:
            conn.close()
    
    def get_pricing(self) -> Dict[str, Any]:
        """Fiyatlandırma bilgilerini al (frontend için)"""
        pricing = self.settings.get_pricing_config()
        
        return {
            "packages": {
                "credits_100": {
                    "name": "100 Kredi",
                    "credits": 100,
                    "price": pricing["price_credits_100"],
                    "price_display": f"{pricing['price_credits_100'] / 100:.0f} ₺"
                },
                "credits_500": {
                    "name": "500 Kredi",
                    "credits": 500,
                    "price": pricing["price_credits_500"],
                    "price_display": f"{pricing['price_credits_500'] / 100:.0f} ₺",
                    "discount": "20% tasarruf"
                },
                "pro_monthly": {
                    "name": "Pro Aylık",
                    "tier": "pro",
                    "price": pricing["price_pro_monthly"],
                    "price_display": f"{pricing['price_pro_monthly'] / 100:.0f} ₺/ay"
                },
                "enterprise_monthly": {
                    "name": "Enterprise Aylık",
                    "tier": "enterprise",
                    "price": pricing["price_enterprise_monthly"],
                    "price_display": f"{pricing['price_enterprise_monthly'] / 100:.0f} ₺/ay"
                }
            },
            "engine_costs": {
                "google": pricing["api_credit_google"],
                "bing": pricing["api_credit_bing"],
                "brave": pricing["api_credit_brave"],
                "baidu": pricing["api_credit_baidu"],
                "naver": pricing["api_credit_naver"],
                "yandex": pricing["api_credit_yandex"],
            },
            "cache_costs": {
                "free": pricing["cache_credit_free"],
                "pro": pricing["cache_credit_pro"],
                "enterprise": pricing["cache_credit_enterprise"],
            },
            "tiers": TIER_CONFIG
        }


# Singleton instance
_credit_manager = None

def get_credit_manager() -> CreditManager:
    """CreditManager singleton instance'ı al"""
    global _credit_manager
    if _credit_manager is None:
        _credit_manager = CreditManager()
    return _credit_manager


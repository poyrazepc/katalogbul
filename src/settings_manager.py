"""
Settings Manager - Şifreli Ayar Yönetimi
API key'ler ve sistem ayarları için CRUD işlemleri
"""
import sqlite3
from typing import Optional, Dict, List, Any
from datetime import datetime

from src.config import DATABASE_PATH
from src.encryption import encrypt, decrypt, mask_value, is_encrypted


# Varsayılan ayarlar (ilk kurulum için)
DEFAULT_SETTINGS = {
    # API Keys
    "api_keys": {
        "paytr_merchant_id": {"value": "", "encrypted": True, "description": "PayTR Mağaza No"},
        "paytr_merchant_key": {"value": "", "encrypted": True, "description": "PayTR Mağaza Parolası"},
        "paytr_merchant_salt": {"value": "", "encrypted": True, "description": "PayTR Gizli Anahtar"},
        "searchapi_key": {"value": "", "encrypted": True, "description": "SearchApi.io API Key"},
        "brave_api_key": {"value": "", "encrypted": True, "description": "Brave Search API Key"},
        "yandex_api_key": {"value": "", "encrypted": True, "description": "Yandex Search API Key"},
        "yandex_folder_id": {"value": "", "encrypted": False, "description": "Yandex Cloud Folder ID"},
        "serper_api_key": {"value": "", "encrypted": True, "description": "Serper.dev API Key"},
    },
    
    # Ödeme/PayTR
    "payment": {
        "paytr_test_mode": {"value": "1", "encrypted": False, "description": "PayTR Test Modu (1=Test, 0=Canlı)"},
        "merchant_ok_url": {"value": "/payment/success", "encrypted": False, "description": "Ödeme Başarılı URL"},
        "merchant_fail_url": {"value": "/payment/fail", "encrypted": False, "description": "Ödeme Başarısız URL"},
    },
    
    # Fiyatlandırma
    "pricing": {
        "initial_credits": {"value": "50", "encrypted": False, "description": "Yeni Kullanıcı Başlangıç Kredisi"},
        "cache_credit_free": {"value": "1", "encrypted": False, "description": "Cache İndirme Kredisi (Free)"},
        "cache_credit_pro": {"value": "1", "encrypted": False, "description": "Cache İndirme Kredisi (Pro)"},
        "cache_credit_enterprise": {"value": "0", "encrypted": False, "description": "Cache İndirme Kredisi (Enterprise)"},
        "api_credit_google": {"value": "10", "encrypted": False, "description": "Google API Kredisi"},
        "api_credit_bing": {"value": "10", "encrypted": False, "description": "Bing API Kredisi"},
        "api_credit_brave": {"value": "10", "encrypted": False, "description": "Brave API Kredisi"},
        "api_credit_baidu": {"value": "15", "encrypted": False, "description": "Baidu API Kredisi"},
        "api_credit_naver": {"value": "15", "encrypted": False, "description": "Naver API Kredisi"},
        "api_credit_yandex": {"value": "15", "encrypted": False, "description": "Yandex API Kredisi"},
        "source_scan_credit": {"value": "5", "encrypted": False, "description": "Kaynak Tarama Kredisi"},
        "price_credits_100": {"value": "4900", "encrypted": False, "description": "100 Kredi Fiyatı (kuruş)"},
        "price_credits_500": {"value": "19900", "encrypted": False, "description": "500 Kredi Fiyatı (kuruş)"},
        "price_pro_monthly": {"value": "9900", "encrypted": False, "description": "Pro Aylık Fiyat (kuruş)"},
        "price_enterprise_monthly": {"value": "29900", "encrypted": False, "description": "Enterprise Aylık Fiyat (kuruş)"},
        "free_daily_limit": {"value": "5", "encrypted": False, "description": "Free Günlük Arama Limiti"},
    },
    
    # Genel Ayarlar
    "general": {
        "site_name": {"value": "KatalogBul", "encrypted": False, "description": "Site Adı"},
        "site_url": {"value": "https://katalogbul.com", "encrypted": False, "description": "Site URL"},
        "support_email": {"value": "destek@katalogbul.com", "encrypted": False, "description": "Destek E-posta"},
        "maintenance_mode": {"value": "0", "encrypted": False, "description": "Bakım Modu (1=Aktif)"},
        "registration_enabled": {"value": "1", "encrypted": False, "description": "Kayıt Açık (1=Evet)"},
    }
}


class SettingsManager:
    """Şifreli ayar yönetimi"""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DATABASE_PATH
    
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_default_settings(self):
        """Varsayılan ayarları yükle (ilk kurulum)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            for category, settings in DEFAULT_SETTINGS.items():
                for key, config in settings.items():
                    # Zaten varsa atla
                    cursor.execute("SELECT id FROM settings WHERE key = ?", (key,))
                    if cursor.fetchone():
                        continue
                    
                    value = config["value"]
                    if config["encrypted"] and value:
                        value = encrypt(value)
                    
                    cursor.execute("""
                        INSERT INTO settings (category, key, value, is_encrypted, description)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        category,
                        key,
                        value,
                        config["encrypted"],
                        config["description"]
                    ))
            
            conn.commit()
            print("Default settings initialized")
        except Exception as e:
            print(f"Error initializing settings: {e}")
        finally:
            conn.close()
    
    def get(self, key: str, default: str = "") -> str:
        """
        Ayar değerini al (şifreli ise çöz)
        
        Args:
            key: Ayar anahtarı
            default: Bulunamazsa varsayılan değer
            
        Returns:
            Çözülmüş değer
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT value, is_encrypted FROM settings WHERE key = ?
            """, (key,))
            
            row = cursor.fetchone()
            if not row:
                return default
            
            value = row["value"]
            if row["is_encrypted"] and value:
                value = decrypt(value)
            
            return value or default
        finally:
            conn.close()
    
    def get_int(self, key: str, default: int = 0) -> int:
        """Ayar değerini integer olarak al"""
        value = self.get(key, str(default))
        try:
            return int(value)
        except ValueError:
            return default
    
    def set(self, key: str, value: str, admin_id: int = None) -> bool:
        """
        Ayar değerini kaydet (gerekirse şifrele)
        
        Args:
            key: Ayar anahtarı
            value: Yeni değer
            admin_id: İşlemi yapan admin
            
        Returns:
            Başarılı mı
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Mevcut ayarı kontrol et
            cursor.execute("SELECT id, is_encrypted FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            
            if not row:
                return False
            
            # Şifrelenecek mi?
            final_value = value
            if row["is_encrypted"] and value:
                final_value = encrypt(value)
            
            cursor.execute("""
                UPDATE settings 
                SET value = ?, updated_at = ?, updated_by = ?
                WHERE key = ?
            """, (final_value, datetime.now().isoformat(), admin_id, key))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"Error setting {key}: {e}")
            return False
        finally:
            conn.close()
    
    def get_all(self, category: str = None, masked: bool = True) -> List[Dict[str, Any]]:
        """
        Tüm ayarları getir
        
        Args:
            category: Kategori filtresi (None = hepsi)
            masked: Şifreli değerler maskelensin mi
            
        Returns:
            Ayar listesi
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            if category:
                cursor.execute("""
                    SELECT * FROM settings WHERE category = ? ORDER BY key
                """, (category,))
            else:
                cursor.execute("SELECT * FROM settings ORDER BY category, key")
            
            results = []
            for row in cursor.fetchall():
                value = row["value"]
                
                if row["is_encrypted"] and value:
                    if masked:
                        # Çöz ve maskele
                        decrypted = decrypt(value)
                        value = mask_value(decrypted)
                    else:
                        # Tamamen çöz
                        value = decrypt(value)
                
                results.append({
                    "id": row["id"],
                    "category": row["category"],
                    "key": row["key"],
                    "value": value,
                    "is_encrypted": bool(row["is_encrypted"]),
                    "description": row["description"],
                    "updated_at": row["updated_at"]
                })
            
            return results
        finally:
            conn.close()
    
    def get_by_category(self, category: str) -> Dict[str, str]:
        """
        Kategori bazlı ayarları dict olarak al
        
        Returns:
            {"key": "value", ...}
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT key, value, is_encrypted FROM settings WHERE category = ?
            """, (category,))
            
            result = {}
            for row in cursor.fetchall():
                value = row["value"]
                if row["is_encrypted"] and value:
                    value = decrypt(value)
                result[row["key"]] = value
            
            return result
        finally:
            conn.close()
    
    def delete(self, key: str) -> bool:
        """Ayarı sil"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def create(
        self,
        category: str,
        key: str,
        value: str,
        is_encrypted: bool = False,
        description: str = "",
        admin_id: int = None
    ) -> bool:
        """Yeni ayar oluştur"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            final_value = value
            if is_encrypted and value:
                final_value = encrypt(value)
            
            cursor.execute("""
                INSERT INTO settings (category, key, value, is_encrypted, description, updated_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (category, key, final_value, is_encrypted, description, admin_id))
            
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Key zaten var
            return False
        finally:
            conn.close()
    
    # Kısayol metodlar
    def get_paytr_config(self) -> Dict[str, str]:
        """PayTR yapılandırmasını al"""
        api_keys = self.get_by_category("api_keys")
        payment = self.get_by_category("payment")
        
        return {
            "merchant_id": api_keys.get("paytr_merchant_id", ""),
            "merchant_key": api_keys.get("paytr_merchant_key", ""),
            "merchant_salt": api_keys.get("paytr_merchant_salt", ""),
            "test_mode": payment.get("paytr_test_mode", "1"),
            "ok_url": payment.get("merchant_ok_url", "/payment/success"),
            "fail_url": payment.get("merchant_fail_url", "/payment/fail"),
        }
    
    def get_pricing_config(self) -> Dict[str, int]:
        """Fiyatlandırma yapılandırmasını al"""
        return {
            "initial_credits": self.get_int("initial_credits", 50),
            "cache_credit_free": self.get_int("cache_credit_free", 1),
            "cache_credit_pro": self.get_int("cache_credit_pro", 1),
            "cache_credit_enterprise": self.get_int("cache_credit_enterprise", 0),
            "api_credit_google": self.get_int("api_credit_google", 10),
            "api_credit_bing": self.get_int("api_credit_bing", 10),
            "api_credit_brave": self.get_int("api_credit_brave", 10),
            "api_credit_baidu": self.get_int("api_credit_baidu", 15),
            "api_credit_naver": self.get_int("api_credit_naver", 15),
            "api_credit_yandex": self.get_int("api_credit_yandex", 15),
            "source_scan_credit": self.get_int("source_scan_credit", 5),
            "price_credits_100": self.get_int("price_credits_100", 4900),
            "price_credits_500": self.get_int("price_credits_500", 19900),
            "price_pro_monthly": self.get_int("price_pro_monthly", 9900),
            "price_enterprise_monthly": self.get_int("price_enterprise_monthly", 29900),
            "free_daily_limit": self.get_int("free_daily_limit", 5),
        }
    
    def get_search_api_keys(self) -> Dict[str, str]:
        """Arama API key'lerini al"""
        api_keys = self.get_by_category("api_keys")
        return {
            "searchapi": api_keys.get("searchapi_key", ""),
            "brave": api_keys.get("brave_api_key", ""),
            "yandex": api_keys.get("yandex_api_key", ""),
            "yandex_folder_id": api_keys.get("yandex_folder_id", ""),
            "serper": api_keys.get("serper_api_key", ""),
        }


# Singleton instance
_settings_manager = None

def get_settings_manager() -> SettingsManager:
    """SettingsManager singleton instance'ı al"""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager


"""
PayTR iFrame API Entegrasyonu
Ödeme işlemleri için PayTR altyapısı
"""
import base64
import hmac
import hashlib
import json
import time
import sqlite3
import requests
from typing import Dict, Optional, Any
from datetime import datetime, timedelta

from src.config import DATABASE_PATH
from src.settings_manager import get_settings_manager


# Paket tanımları
PACKAGES = {
    "credits_100": {
        "name": "100 Kredi",
        "credits": 100,
        "tier": None,
        "duration_days": None
    },
    "credits_500": {
        "name": "500 Kredi", 
        "credits": 500,
        "tier": None,
        "duration_days": None
    },
    "pro_monthly": {
        "name": "Pro Aylık Abonelik",
        "credits": 0,
        "tier": "pro",
        "duration_days": 30
    },
    "enterprise_monthly": {
        "name": "Enterprise Aylık Abonelik",
        "credits": 0,
        "tier": "enterprise",
        "duration_days": 30
    }
}


class PayTRClient:
    """PayTR iFrame API istemcisi"""
    
    API_URL = "https://www.paytr.com/odeme/api/get-token"
    
    def __init__(self):
        self.settings = get_settings_manager()
        self.db_path = DATABASE_PATH
    
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _get_config(self) -> Dict[str, str]:
        """PayTR yapılandırmasını al"""
        return self.settings.get_paytr_config()
    
    def _get_package_price(self, package_type: str) -> int:
        """Paket fiyatını al (kuruş cinsinden)"""
        pricing = self.settings.get_pricing_config()
        
        price_keys = {
            "credits_100": "price_credits_100",
            "credits_500": "price_credits_500",
            "pro_monthly": "price_pro_monthly",
            "enterprise_monthly": "price_enterprise_monthly"
        }
        
        key = price_keys.get(package_type)
        if key:
            return pricing.get(key, 0)
        return 0
    
    def create_payment_token(
        self,
        user_id: int,
        user_email: str,
        package_type: str,
        user_ip: str,
        user_name: str = "KatalogBul Kullanıcı"
    ) -> Dict[str, Any]:
        """
        PayTR iFrame token oluştur
        
        Args:
            user_id: Kullanıcı ID
            user_email: E-posta
            package_type: Paket tipi (credits_100, pro_monthly, vb.)
            user_ip: Kullanıcı IP adresi
            user_name: Kullanıcı adı
            
        Returns:
            {
                "status": "success" | "failed",
                "token": "xxx",  # Başarılıysa
                "merchant_oid": "xxx",
                "error": "xxx"  # Başarısızsa
            }
        """
        config = self._get_config()
        
        # Config kontrolü
        if not config.get("merchant_id") or not config.get("merchant_key"):
            return {
                "status": "failed",
                "error": "PayTR yapılandırması eksik. Admin panelinden ayarlayın."
            }
        
        # Paket kontrolü
        package = PACKAGES.get(package_type)
        if not package:
            return {
                "status": "failed",
                "error": "Geçersiz paket tipi"
            }
        
        # Fiyat al
        payment_amount = self._get_package_price(package_type)
        if payment_amount <= 0:
            return {
                "status": "failed",
                "error": "Paket fiyatı tanımlı değil"
            }
        
        # Benzersiz sipariş numarası
        merchant_oid = f"KB_{user_id}_{int(time.time())}"
        
        # Sepet oluştur
        basket = [[package["name"], str(payment_amount / 100), 1]]
        user_basket = base64.b64encode(json.dumps(basket).encode()).decode()
        
        # PayTR parametreleri
        merchant_id = config["merchant_id"]
        merchant_key = config["merchant_key"].encode()
        merchant_salt = config["merchant_salt"].encode()
        test_mode = config.get("test_mode", "1")
        
        no_installment = "1"  # Taksit yok
        max_installment = "0"
        currency = "TL"
        
        # Site URL
        site_url = self.settings.get("site_url", "http://localhost:8000")
        merchant_ok_url = f"{site_url}{config.get('ok_url', '/payment/success')}"
        merchant_fail_url = f"{site_url}{config.get('fail_url', '/payment/fail')}"
        
        # Hash string oluştur
        hash_str = (
            merchant_id + user_ip + merchant_oid + user_email + 
            str(payment_amount) + user_basket + no_installment + 
            max_installment + currency + test_mode
        )
        
        # HMAC-SHA256 hash
        paytr_token = base64.b64encode(
            hmac.new(merchant_key, (hash_str.encode() + merchant_salt), hashlib.sha256).digest()
        ).decode()
        
        # API isteği
        params = {
            "merchant_id": merchant_id,
            "user_ip": user_ip,
            "merchant_oid": merchant_oid,
            "email": user_email,
            "payment_amount": str(payment_amount),
            "paytr_token": paytr_token,
            "user_basket": user_basket,
            "debug_on": "1",
            "no_installment": no_installment,
            "max_installment": max_installment,
            "user_name": user_name,
            "user_address": "Türkiye",
            "user_phone": "05000000000",
            "merchant_ok_url": merchant_ok_url,
            "merchant_fail_url": merchant_fail_url,
            "timeout_limit": "30",
            "currency": currency,
            "test_mode": test_mode,
            "lang": "tr"
        }
        
        try:
            response = requests.post(self.API_URL, data=params, timeout=30)
            result = response.json()
            
            if result.get("status") == "success":
                # Bekleyen ödemeyi kaydet
                self._save_pending_payment(
                    user_id=user_id,
                    merchant_oid=merchant_oid,
                    package_type=package_type,
                    amount=payment_amount
                )
                
                return {
                    "status": "success",
                    "token": result["token"],
                    "merchant_oid": merchant_oid
                }
            else:
                return {
                    "status": "failed",
                    "error": result.get("reason", "Bilinmeyen PayTR hatası")
                }
                
        except requests.RequestException as e:
            return {
                "status": "failed",
                "error": f"PayTR bağlantı hatası: {str(e)}"
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": f"Beklenmeyen hata: {str(e)}"
            }
    
    def verify_callback(self, post_data: Dict[str, str]) -> bool:
        """
        PayTR callback doğrulama
        
        Args:
            post_data: PayTR'dan gelen POST verisi
            
        Returns:
            Hash geçerli mi
        """
        config = self._get_config()
        
        merchant_key = config["merchant_key"].encode()
        merchant_salt = config["merchant_salt"]
        
        merchant_oid = post_data.get("merchant_oid", "")
        status = post_data.get("status", "")
        total_amount = post_data.get("total_amount", "")
        hash_received = post_data.get("hash", "")
        
        # Hash oluştur
        hash_str = merchant_oid + merchant_salt + status + total_amount
        hash_calculated = base64.b64encode(
            hmac.new(merchant_key, hash_str.encode(), hashlib.sha256).digest()
        ).decode()
        
        return hash_received == hash_calculated
    
    def process_callback(self, post_data: Dict[str, str]) -> Dict[str, Any]:
        """
        PayTR callback işle
        
        Returns:
            {
                "success": bool,
                "message": str,
                "user_id": int  # Başarılıysa
            }
        """
        # Hash doğrula
        if not self.verify_callback(post_data):
            return {"success": False, "message": "Hash doğrulama hatası"}
        
        merchant_oid = post_data.get("merchant_oid")
        status = post_data.get("status")
        total_amount = post_data.get("total_amount")
        
        # Bekleyen ödemeyi bul
        payment = self._get_pending_payment(merchant_oid)
        if not payment:
            return {"success": False, "message": "Ödeme kaydı bulunamadı"}
        
        # Zaten işlendi mi?
        if payment["status"] != "pending":
            return {"success": True, "message": "Ödeme zaten işlendi"}
        
        user_id = payment["user_id"]
        package_type = payment["package_type"]
        
        if status == "success":
            # Ödeme başarılı
            package = PACKAGES.get(package_type, {})
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            try:
                if package.get("credits"):
                    # Kredi ekle
                    credits = package["credits"]
                    cursor.execute("""
                        UPDATE users SET credit_balance = credit_balance + ?
                        WHERE id = ?
                    """, (credits, user_id))
                
                if package.get("tier"):
                    # Tier yükselt
                    tier = package["tier"]
                    duration = package.get("duration_days", 30)
                    expires_at = (datetime.now() + timedelta(days=duration)).isoformat()
                    
                    cursor.execute("""
                        UPDATE users 
                        SET subscription_tier = ?, subscription_expires_at = ?
                        WHERE id = ?
                    """, (tier, expires_at, user_id))
                
                # Ödemeyi tamamlandı işaretle
                cursor.execute("""
                    UPDATE payments 
                    SET status = 'success', 
                        completed_at = ?,
                        paytr_response = ?
                    WHERE merchant_oid = ?
                """, (
                    datetime.now().isoformat(),
                    json.dumps(post_data),
                    merchant_oid
                ))
                
                conn.commit()
                
                return {
                    "success": True,
                    "message": "Ödeme başarıyla işlendi",
                    "user_id": user_id
                }
                
            finally:
                conn.close()
        else:
            # Ödeme başarısız
            self._update_payment_status(merchant_oid, "failed", post_data)
            
            return {
                "success": False,
                "message": post_data.get("failed_reason_msg", "Ödeme başarısız")
            }
    
    def _save_pending_payment(
        self,
        user_id: int,
        merchant_oid: str,
        package_type: str,
        amount: int
    ):
        """Bekleyen ödemeyi kaydet"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO payments (user_id, merchant_oid, package_type, amount, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (user_id, merchant_oid, package_type, amount))
            conn.commit()
        finally:
            conn.close()
    
    def _get_pending_payment(self, merchant_oid: str) -> Optional[Dict]:
        """Bekleyen ödemeyi getir"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM payments WHERE merchant_oid = ?
            """, (merchant_oid,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def _update_payment_status(
        self,
        merchant_oid: str,
        status: str,
        response: Dict = None
    ):
        """Ödeme durumunu güncelle"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE payments 
                SET status = ?, 
                    completed_at = ?,
                    paytr_response = ?
                WHERE merchant_oid = ?
            """, (
                status,
                datetime.now().isoformat(),
                json.dumps(response) if response else None,
                merchant_oid
            ))
            conn.commit()
        finally:
            conn.close()
    
    def get_user_payments(self, user_id: int, limit: int = 20) -> list:
        """Kullanıcının ödeme geçmişi"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT id, merchant_oid, package_type, amount, status, 
                       created_at, completed_at
                FROM payments 
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, limit))
            
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()


# Singleton instance
_paytr_client = None

def get_paytr_client() -> PayTRClient:
    """PayTRClient singleton instance'ı al"""
    global _paytr_client
    if _paytr_client is None:
        _paytr_client = PayTRClient()
    return _paytr_client


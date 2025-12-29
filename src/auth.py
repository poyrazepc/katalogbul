"""
JWT Authentication System
Kullanıcı kimlik doğrulama ve token yönetimi
"""
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from src.config import DATABASE_PATH
from src.models import TokenData, SubscriptionTier, UserRole


# ================================================================
# CONFIGURATION
# ================================================================

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "katalogbul-secret-key-change-in-production-2025")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# Password hashing - pbkdf2_sha256 kullan (bcrypt uyumluluk sorunu nedeniyle)
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


# ================================================================
# PASSWORD FUNCTIONS
# ================================================================

def hash_password(password: str) -> str:
    """Şifreyi hashle"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Şifreyi doğrula"""
    return pwd_context.verify(plain_password, hashed_password)


# ================================================================
# TOKEN FUNCTIONS
# ================================================================

def create_access_token(
    user_id: int,
    email: str,
    tier: str,
    role: str,
    expires_delta: timedelta = None
) -> str:
    """
    JWT access token oluştur
    
    Args:
        user_id: Kullanıcı ID
        email: E-posta
        tier: Abonelik tipi
        role: Kullanıcı rolü
        expires_delta: Token süresi
        
    Returns:
        JWT token string
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    
    payload = {
        "sub": str(user_id),
        "email": email,
        "tier": tier,
        "role": role,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[TokenData]:
    """
    JWT token'ı decode et
    
    Args:
        token: JWT token string
        
    Returns:
        TokenData veya None
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        user_id = int(payload.get("sub"))
        email = payload.get("email")
        tier = payload.get("tier", "free")
        role = payload.get("role", "user")
        
        return TokenData(
            user_id=user_id,
            email=email,
            tier=SubscriptionTier(tier),
            role=UserRole(role)
        )
    except JWTError as e:
        print(f"JWT decode error: {e}")
        return None
    except Exception as e:
        print(f"Token decode error: {e}")
        return None


# ================================================================
# USER DATABASE FUNCTIONS
# ================================================================

class UserManager:
    """Kullanıcı veritabanı işlemleri"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DATABASE_PATH
    
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        phone: str = None,
        initial_credits: int = 50
    ) -> Optional[Dict[str, Any]]:
        """
        Yeni kullanıcı oluştur
        
        Returns:
            Kullanıcı dict veya None (hata durumunda)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            hashed = hash_password(password)
            
            cursor.execute("""
                INSERT INTO users (username, email, phone, hashed_password, credit_balance)
                VALUES (?, ?, ?, ?, ?)
            """, (username, email.lower(), phone, hashed, initial_credits))
            
            user_id = cursor.lastrowid
            conn.commit()
            
            return self.get_user_by_id(user_id)
        except sqlite3.IntegrityError as e:
            if "username" in str(e):
                raise ValueError("Bu kullanıcı adı zaten kullanılıyor")
            elif "email" in str(e):
                raise ValueError("Bu e-posta adresi zaten kayıtlı")
            else:
                raise ValueError("Kayıt sırasında hata oluştu")
        finally:
            conn.close()
    
    def authenticate(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Kullanıcı kimlik doğrulama
        
        Returns:
            Kullanıcı dict veya None
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM users WHERE email = ? AND is_active = 1
            """, (email.lower(),))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            if not verify_password(password, row["hashed_password"]):
                return None
            
            # Son giriş güncelle
            cursor.execute("""
                UPDATE users SET last_login = ? WHERE id = ?
            """, (datetime.now().isoformat(), row["id"]))
            conn.commit()
            
            return dict(row)
        finally:
            conn.close()
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """ID ile kullanıcı getir"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """E-posta ile kullanıcı getir"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM users WHERE email = ?", (email.lower(),))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def update_user(self, user_id: int, **kwargs) -> bool:
        """Kullanıcı güncelle"""
        if not kwargs:
            return False
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            set_parts = []
            values = []
            
            for key, value in kwargs.items():
                if key in ["username", "email", "role", "credit_balance", 
                          "subscription_tier", "subscription_expires_at", "is_active"]:
                    set_parts.append(f"{key} = ?")
                    values.append(value)
            
            if not set_parts:
                return False
            
            values.append(user_id)
            query = f"UPDATE users SET {', '.join(set_parts)} WHERE id = ?"
            
            cursor.execute(query, values)
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def update_credits(self, user_id: int, amount: int) -> bool:
        """
        Kredi güncelle (pozitif = ekle, negatif = çıkar)
        
        Returns:
            Başarılı mı
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            if amount < 0:
                # Çıkarma - yeterli kredi kontrolü
                cursor.execute("""
                    UPDATE users 
                    SET credit_balance = credit_balance + ?
                    WHERE id = ? AND credit_balance >= ?
                """, (amount, user_id, abs(amount)))
            else:
                # Ekleme
                cursor.execute("""
                    UPDATE users SET credit_balance = credit_balance + ?
                    WHERE id = ?
                """, (amount, user_id))
            
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def get_credit_balance(self, user_id: int) -> int:
        """Kredi bakiyesi getir"""
        user = self.get_user_by_id(user_id)
        return user["credit_balance"] if user else 0
    
    def increment_daily_search(self, user_id: int) -> int:
        """
        Günlük arama sayısını artır
        
        Returns:
            Yeni arama sayısı
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            today = datetime.now().date().isoformat()
            
            # Bugünün araması mı kontrol et
            cursor.execute("""
                SELECT daily_search_count, last_search_date FROM users WHERE id = ?
            """, (user_id,))
            
            row = cursor.fetchone()
            if not row:
                return 0
            
            if row["last_search_date"] == today:
                new_count = row["daily_search_count"] + 1
            else:
                new_count = 1
            
            cursor.execute("""
                UPDATE users 
                SET daily_search_count = ?, last_search_date = ?
                WHERE id = ?
            """, (new_count, today, user_id))
            
            conn.commit()
            return new_count
        finally:
            conn.close()
    
    def check_daily_limit(self, user_id: int, limit: int) -> bool:
        """
        Günlük limit kontrolü
        
        Returns:
            Limit aşılmadı mı
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            today = datetime.now().date().isoformat()
            
            cursor.execute("""
                SELECT daily_search_count, last_search_date FROM users WHERE id = ?
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
    
    def list_users(
        self,
        page: int = 1,
        per_page: int = 20,
        tier: str = None,
        role: str = None,
        is_active: bool = None
    ) -> Dict[str, Any]:
        """
        Kullanıcı listesi (admin için)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Count query
            count_query = "SELECT COUNT(*) FROM users WHERE 1=1"
            list_query = "SELECT * FROM users WHERE 1=1"
            params = []
            
            if tier:
                count_query += " AND subscription_tier = ?"
                list_query += " AND subscription_tier = ?"
                params.append(tier)
            
            if role:
                count_query += " AND role = ?"
                list_query += " AND role = ?"
                params.append(role)
            
            if is_active is not None:
                count_query += " AND is_active = ?"
                list_query += " AND is_active = ?"
                params.append(is_active)
            
            # Total count
            cursor.execute(count_query, params)
            total = cursor.fetchone()[0]
            
            # List with pagination
            list_query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([per_page, (page - 1) * per_page])
            
            cursor.execute(list_query, params)
            users = [dict(row) for row in cursor.fetchall()]
            
            # Şifreleri kaldır
            for user in users:
                user.pop("hashed_password", None)
            
            return {
                "items": users,
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page
            }
        finally:
            conn.close()
    
    def create_admin(
        self,
        username: str,
        email: str,
        password: str
    ) -> Optional[Dict[str, Any]]:
        """Superadmin oluştur (ilk kurulum için)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            hashed = hash_password(password)
            
            cursor.execute("""
                INSERT INTO users (username, email, hashed_password, role, credit_balance, subscription_tier)
                VALUES (?, ?, ?, 'superadmin', 999999, 'enterprise')
            """, (username, email.lower(), hashed))
            
            user_id = cursor.lastrowid
            conn.commit()
            
            return self.get_user_by_id(user_id)
        except sqlite3.IntegrityError:
            return None
        finally:
            conn.close()


# Singleton instance
_user_manager = None

def get_user_manager() -> UserManager:
    """UserManager singleton instance'ı al"""
    global _user_manager
    if _user_manager is None:
        _user_manager = UserManager()
    return _user_manager


"""
Pydantic Modeller
API request/response şemaları
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


# ================================================================
# ENUMS
# ================================================================

class SubscriptionTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


# ================================================================
# AUTH MODELS
# ================================================================

class UserRegister(BaseModel):
    """Kullanıcı kayıt"""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)
    phone: Optional[str] = Field(None, max_length=20)


class UserLogin(BaseModel):
    """Kullanıcı giriş"""
    email: EmailStr
    password: str


class Token(BaseModel):
    """JWT Token yanıtı"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400  # 24 saat


class TokenData(BaseModel):
    """Token içeriği"""
    user_id: int
    email: str
    tier: SubscriptionTier
    role: UserRole


class UserResponse(BaseModel):
    """Kullanıcı bilgisi (şifre hariç)"""
    id: int
    username: str
    email: str
    role: UserRole
    credit_balance: int
    subscription_tier: SubscriptionTier
    subscription_expires_at: Optional[datetime]
    daily_search_count: int
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime]


class UserUpdate(BaseModel):
    """Kullanıcı güncelleme (admin için)"""
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    credit_balance: Optional[int] = None
    subscription_tier: Optional[SubscriptionTier] = None
    is_active: Optional[bool] = None


# ================================================================
# PAYMENT MODELS
# ================================================================

class PaymentCreate(BaseModel):
    """Ödeme başlatma"""
    package: str  # credits_100, credits_500, pro_monthly, enterprise_monthly


class PaymentResponse(BaseModel):
    """Ödeme yanıtı"""
    iframe_token: Optional[str] = None
    merchant_oid: Optional[str] = None
    error: Optional[str] = None


class PaymentHistory(BaseModel):
    """Ödeme geçmişi"""
    id: int
    merchant_oid: str
    package_type: str
    amount: int
    status: PaymentStatus
    created_at: datetime
    completed_at: Optional[datetime]


# ================================================================
# SEARCH MODELS
# ================================================================

class SearchRequest(BaseModel):
    """Arama isteği"""
    brand: str
    model: str = ""
    doc_type: str = "parts"
    languages: List[str] = []
    engines: List[str] = []


class GlobalSearchRequest(BaseModel):
    """Global arama isteği"""
    query: str
    languages: List[str] = []
    engines: List[str] = []


class SearchResult(BaseModel):
    """Arama sonucu"""
    title: str
    url: str
    description: str
    source: str
    engine: Optional[str] = None
    language: Optional[str] = None
    file_size_bytes: Optional[int] = None
    page_count: Optional[int] = None
    is_locked: bool = False  # Kilitli içerik


class SearchResponse(BaseModel):
    """Arama yanıtı"""
    results: List[SearchResult]
    total_count: int
    credits_used: int
    remaining_credits: int
    is_cached: bool


# ================================================================
# SETTINGS MODELS
# ================================================================

class SettingUpdate(BaseModel):
    """Ayar güncelleme"""
    value: str


class SettingCreate(BaseModel):
    """Yeni ayar oluşturma"""
    category: str
    key: str
    value: str
    is_encrypted: bool = False
    description: str = ""


class SettingResponse(BaseModel):
    """Ayar yanıtı"""
    id: int
    category: str
    key: str
    value: str
    is_encrypted: bool
    description: str
    updated_at: Optional[datetime]


# ================================================================
# ADMIN MODELS
# ================================================================

class DashboardStats(BaseModel):
    """Dashboard istatistikleri"""
    total_users: int
    active_subscriptions: int
    today_searches: int
    today_revenue: int
    total_credits_used: int
    cache_entries: int


class CreditAdjustment(BaseModel):
    """Kredi ekleme/çıkarma"""
    amount: int  # Pozitif = ekle, negatif = çıkar
    reason: str = ""


class SearchLogEntry(BaseModel):
    """Arama log kaydı"""
    id: int
    user_id: Optional[int]
    username: Optional[str]
    query: str
    doc_type: Optional[str]
    engines_used: List[str]
    result_count: int
    credits_used: int
    is_cached: bool
    ip_address: Optional[str]
    created_at: datetime


class AdminLogEntry(BaseModel):
    """Admin log kaydı"""
    id: int
    admin_id: int
    admin_username: str
    action: str
    target_table: Optional[str]
    target_id: Optional[int]
    old_value: Optional[str]
    new_value: Optional[str]
    ip_address: Optional[str]
    created_at: datetime


# ================================================================
# PAGINATION
# ================================================================

class PaginationParams(BaseModel):
    """Sayfalama parametreleri"""
    page: int = 1
    per_page: int = 20
    
    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


class PaginatedResponse(BaseModel):
    """Sayfalanmış yanıt"""
    items: List[Any]
    total: int
    page: int
    per_page: int
    pages: int


"""
FastAPI Dependencies
Kimlik doğrulama ve yetkilendirme dependency'leri
"""
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.auth import decode_token, get_user_manager
from src.models import TokenData, UserRole


# HTTP Bearer auth
security = HTTPBearer(auto_error=False)


async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[dict]:
    """
    Opsiyonel kullanıcı doğrulama
    Guest erişimine izin verir
    
    Returns:
        Kullanıcı dict veya None (guest)
    """
    if not credentials:
        return None
    
    try:
        token_data = decode_token(credentials.credentials)
        if not token_data:
            return None
        
        user_manager = get_user_manager()
        user = user_manager.get_user_by_id(token_data.user_id)
        
        if not user or not user.get("is_active"):
            return None
        
        return user
    except Exception as e:
        print(f"Auth error: {e}")
        return None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    Zorunlu kullanıcı doğrulama
    Giriş yapmamış kullanıcılar erişemez
    
    Returns:
        Kullanıcı dict
        
    Raises:
        HTTPException 401: Token geçersiz veya yok
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Giriş yapmanız gerekiyor",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    try:
        token_data = decode_token(credentials.credentials)
        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Geçersiz veya süresi dolmuş token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        user_manager = get_user_manager()
        user = user_manager.get_user_by_id(token_data.user_id)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Kullanıcı bulunamadı"
            )
        
        if not user.get("is_active"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hesabınız devre dışı bırakılmış"
            )
        
        return user
    except HTTPException:
        raise
    except Exception as e:
        print(f"Auth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kimlik doğrulama hatası"
        )


async def get_admin_user(
    user: dict = Depends(get_current_user)
) -> dict:
    """
    Admin yetkisi kontrolü
    Sadece admin ve superadmin erişebilir
    
    Returns:
        Admin kullanıcı dict
        
    Raises:
        HTTPException 403: Yetki yok
    """
    role = user.get("role", "user")
    
    if role not in ["admin", "superadmin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için yönetici yetkisi gerekiyor"
        )
    
    return user


async def get_superadmin_user(
    user: dict = Depends(get_current_user)
) -> dict:
    """
    Superadmin yetkisi kontrolü
    Sadece superadmin erişebilir
    
    Returns:
        Superadmin kullanıcı dict
        
    Raises:
        HTTPException 403: Yetki yok
    """
    if user.get("role") != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için süper yönetici yetkisi gerekiyor"
        )
    
    return user


def check_credits(required: int):
    """
    Kredi kontrolü dependency factory
    
    Usage:
        @app.post("/api/search")
        async def search(user = Depends(check_credits(10))):
            ...
    """
    async def _check(user: dict = Depends(get_current_user)) -> dict:
        balance = user.get("credit_balance", 0)
        
        if balance < required:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "message": "Yetersiz kredi",
                    "required": required,
                    "balance": balance
                }
            )
        
        return user
    
    return _check


def require_tier(allowed_tiers: list):
    """
    Tier kontrolü dependency factory
    
    Usage:
        @app.post("/api/source-scan")
        async def scan(user = Depends(require_tier(["pro", "enterprise"]))):
            ...
    """
    async def _check(user: dict = Depends(get_current_user)) -> dict:
        tier = user.get("subscription_tier", "free")
        
        if tier not in allowed_tiers:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": f"Bu özellik için {', '.join(allowed_tiers)} aboneliği gerekiyor",
                    "current_tier": tier,
                    "required_tiers": allowed_tiers
                }
            )
        
        return user
    
    return _check


def get_client_ip(request: Request) -> str:
    """İstemci IP adresini al"""
    # Proxy arkasındaysa X-Forwarded-For header'ını kontrol et
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    return request.client.host if request.client else "unknown"


def get_user_agent(request: Request) -> str:
    """User-Agent header'ını al"""
    return request.headers.get("User-Agent", "unknown")


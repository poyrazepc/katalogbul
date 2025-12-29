"""
AES-256 Şifreleme Utility
API key'ler ve hassas veriler için
"""
import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()


def generate_key() -> str:
    """Yeni encryption key oluştur (ilk kurulum için)"""
    return Fernet.generate_key().decode()


def _get_cipher():
    """Fernet cipher instance al"""
    key = os.getenv("ENCRYPTION_KEY")
    
    if not key:
        # Geliştirme ortamı için varsayılan key (PRODUCTION'DA DEĞİŞTİRİN!)
        key = "development-key-change-in-production-32ch"
    
    # Key'i Fernet formatına dönüştür
    if len(key) != 44:  # Fernet key length
        # PBKDF2 ile key türet
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'katalogbul-salt-v1',
            iterations=100000,
        )
        derived_key = base64.urlsafe_b64encode(kdf.derive(key.encode()))
        return Fernet(derived_key)
    
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    """
    String değeri şifrele
    
    Args:
        value: Şifrelenecek değer
        
    Returns:
        Base64 encoded şifreli string
    """
    if not value:
        return ""
    
    cipher = _get_cipher()
    encrypted = cipher.encrypt(value.encode())
    return encrypted.decode()


def decrypt(encrypted_value: str) -> str:
    """
    Şifreli değeri çöz
    
    Args:
        encrypted_value: Şifrelenmiş değer
        
    Returns:
        Çözülmüş string
    """
    if not encrypted_value:
        return ""
    
    try:
        cipher = _get_cipher()
        decrypted = cipher.decrypt(encrypted_value.encode())
        return decrypted.decode()
    except Exception as e:
        print(f"Decryption error: {e}")
        return ""


def mask_value(value: str, show_chars: int = 4) -> str:
    """
    Değeri maskele (UI gösterimi için)
    
    Args:
        value: Maskelenecek değer
        show_chars: Gösterilecek karakter sayısı (baştan)
        
    Returns:
        Maskelenmiş string (örn: "ABCD••••••••")
    """
    if not value:
        return ""
    
    if len(value) <= show_chars:
        return "•" * len(value)
    
    return value[:show_chars] + "•" * (len(value) - show_chars)


def is_encrypted(value: str) -> bool:
    """
    Değerin Fernet formatında şifreli olup olmadığını kontrol et
    """
    if not value:
        return False
    
    # Fernet tokenları "gAAAAA" ile başlar
    return value.startswith("gAAAAA")


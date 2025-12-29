# MakineParça - Sistem Dokümantasyonu

**Ağır İş Makineleri Parça Arama ve Katalog Analiz Sistemi**

---

## 📋 Değişiklik Günlüğü (Changelog)

### v2.1.0 (28 Aralık 2024)
**Arama Sistemi Düzeltmeleri:**
- ✅ Yandex çift filtre sorunu düzeltildi (`filetype:pdf` + `mime:pdf`)
- ✅ PDF kontrolü genişletildi (URL, title, description)
- ✅ Brave pagination limiti artırıldı (100 → 200)
- ✅ Çift `filetype:pdf` ekleme sorunu düzeltildi

**Proje Yapılandırması:**
- ✅ `.cursorignore` dosyası oluşturuldu
- ✅ Cursor kural dosyaları güncellendi
- ✅ `GOREV.md` dosyası eklendi

**Etkilenen Dosyalar:**
- `src/yandex_client.py`
- `src/brave_client.py`
- `src/serper_client.py`
- `src/search/google.py`
- `src/search/brave.py`
- `.cursor/rules/*.mdc`

---

## 1. Proje Genel Bakış

MakineParça, ağır iş makineleri için yedek parça kataloglarını arama ve analiz etme platformudur. Sistem iki ana özellik sunar:

1. **Çoklu Motor PDF Arama**: 6 farklı arama motoruyla (Google, Brave, Yandex, Bing, Baidu, Naver) PDF katalog araması
2. **Akıllı Katalog Analizi**: Claude Vision API ile PDF kataloglarını otomatik analiz ederek parça bilgilerini çıkarma

---

## 2. Teknoloji Stack

| Katman | Teknoloji | Versiyon |
|--------|-----------|----------|
| **Backend** | FastAPI | 0.100+ |
| **Runtime** | Python | 3.11 |
| **Veritabanı** | SQLite | 3 |
| **Frontend** | HTML5, Tailwind CSS, Vanilla JS | - |
| **AI** | Claude Vision API (Anthropic) | claude-sonnet-4 |
| **Arama Motorları** | Serper, Brave, Yandex, SearchAPI | - |
| **Ödeme** | PayTR iFrame API | - |
| **Auth** | JWT (python-jose) | - |
| **Şifre Hash** | bcrypt (passlib) | - |
| **Şifreleme** | Fernet (cryptography) | - |
| **PDF İşleme** | PyMuPDF (fitz) | - |
| **SSE** | sse-starlette | - |

---

## 3. Dosya Yapısı

```
pdfara/
├── api/
│   └── main.py                 # FastAPI endpoint'leri (1800+ satır)
│
├── src/
│   ├── auth.py                 # JWT auth, kullanıcı yönetimi
│   ├── database.py             # SQLite şema (20+ tablo)
│   ├── config.py               # Konfigürasyon (API key fallback'ler)
│   │
│   ├── catalog_service.py      # PDF katalog analiz servisi
│   ├── catalog_analyzer.py     # Claude Vision entegrasyonu
│   │
│   ├── multi_search.py         # Çoklu motor koordinasyonu
│   ├── serper_client.py        # Google arama (Serper.dev)
│   ├── brave_client.py         # Brave arama
│   ├── yandex_client.py        # Yandex arama
│   ├── searchapi_client.py     # SearchAPI (Bing, Baidu, Naver)
│   │
│   ├── credit_manager.py       # Kredi sistemi
│   ├── settings_manager.py     # Şifreli ayar yönetimi
│   ├── encryption.py           # Fernet şifreleme
│   ├── payment.py              # PayTR entegrasyonu
│   │
│   ├── cache_manager.py        # Arama önbellek yönetimi
│   ├── pdf_analyzer.py         # PDF meta analizi
│   ├── keywords.py             # Arama anahtar kelimeleri
│   ├── models.py               # Pydantic modelleri
│   └── dependencies.py         # FastAPI dependency'ler
│
├── frontend/
│   ├── index.html              # Landing page
│   ├── login.html              # Giriş sayfası
│   ├── register.html           # Kayıt sayfası
│   ├── forgot-password.html    # Şifre sıfırlama
│   ├── search.html             # Arama sonuçları
│   ├── dashboard.html          # Kullanıcı paneli
│   ├── catalog-viewer.html     # PDF katalog görüntüleyici
│   ├── admin.html              # Admin paneli
│   ├── contact.html            # İletişim
│   └── legal/                  # Yasal belgeler
│
├── data/
│   └── pepc_catalog.db         # Ana SQLite veritabanı
│
├── uploads/                    # Yüklenen PDF'ler
├── thumbnails/                 # PDF küçük resimleri
│
├── .env                        # Ortam değişkenleri (API key'ler)
├── requirements.txt            # Python bağımlılıkları
└── start.bat                   # Başlatma scripti
```

---

## 4. Veritabanı Şeması

### 4.1 Entity Relationship Diyagramı

```
┌─────────────┐       ┌─────────────────┐       ┌──────────────────┐
│   users     │───────│  user_catalogs  │───────│  catalog_rules   │
└─────────────┘       └─────────────────┘       └──────────────────┘
      │                       │
      │                       ├───────────────────┐
      │                       │                   │
      ▼                       ▼                   ▼
┌─────────────┐       ┌─────────────────┐  ┌──────────────────┐
│  payments   │       │catalog_categories│  │  catalog_parts   │
└─────────────┘       └─────────────────┘  └──────────────────┘
      │                       │
      │                       ▼
      ▼               ┌─────────────────┐
┌─────────────┐       │catalog_fingerprints│
│credit_requests│     └─────────────────┘
└─────────────┘
      │
      ▼
┌─────────────┐       ┌─────────────────┐
│ search_logs │       │  search_cache   │
└─────────────┘       └─────────────────┘
```

### 4.2 Kullanıcı ve Kredi Sistemi Tabloları

#### users
| Kolon | Tip | Açıklama |
|-------|-----|----------|
| id | INTEGER PRIMARY KEY | Benzersiz ID |
| username | TEXT UNIQUE | Kullanıcı adı |
| email | TEXT UNIQUE | E-posta |
| phone | TEXT | Telefon |
| hashed_password | TEXT | bcrypt hash |
| role | TEXT | user/admin/superadmin |
| credit_balance | INTEGER | Kredi bakiyesi (varsayılan: 50) |
| subscription_tier | TEXT | free/pro/enterprise |
| daily_search_count | INTEGER | Günlük arama sayısı |
| is_active | BOOLEAN | Aktif mi |
| created_at | DATETIME | Kayıt tarihi |
| last_login | DATETIME | Son giriş |

#### settings
| Kolon | Tip | Açıklama |
|-------|-----|----------|
| id | INTEGER PRIMARY KEY | Benzersiz ID |
| category | TEXT | api_keys/payment/pricing/general |
| key | TEXT UNIQUE | Ayar anahtarı |
| value | TEXT | Değer (şifreli olabilir) |
| is_encrypted | BOOLEAN | Şifreli mi |
| description | TEXT | Açıklama |
| updated_at | DATETIME | Güncelleme tarihi |

#### credit_requests
| Kolon | Tip | Açıklama |
|-------|-----|----------|
| id | INTEGER PRIMARY KEY | Benzersiz ID |
| user_id | INTEGER FK | Kullanıcı |
| package_type | TEXT | credits_100/credits_500/credits_1000 |
| credit_amount | INTEGER | Kredi miktarı |
| price_amount | INTEGER | Fiyat (kuruş) |
| status | TEXT | pending/approved/rejected |
| admin_note | TEXT | Admin notu |
| processed_by | INTEGER FK | İşleyen admin |
| created_at | DATETIME | Talep tarihi |

#### payments
| Kolon | Tip | Açıklama |
|-------|-----|----------|
| id | INTEGER PRIMARY KEY | Benzersiz ID |
| user_id | INTEGER FK | Kullanıcı |
| merchant_oid | TEXT UNIQUE | PayTR sipariş ID |
| package_type | TEXT | Paket tipi |
| amount | INTEGER | Tutar (kuruş) |
| status | TEXT | pending/success/failed |
| paytr_response | TEXT | PayTR JSON yanıt |

### 4.3 Katalog Öğrenme Sistemi Tabloları

#### user_catalogs
| Kolon | Tip | Açıklama |
|-------|-----|----------|
| id | INTEGER PRIMARY KEY | Benzersiz ID |
| user_id | INTEGER FK | Yükleyen kullanıcı |
| filename | TEXT | Sunucudaki dosya adı |
| original_name | TEXT | Orijinal dosya adı |
| file_path | TEXT | Dosya yolu |
| file_size | INTEGER | Boyut (byte) |
| total_pages | INTEGER | Sayfa sayısı |
| brand | TEXT | Marka (Volvo, CAT, vb.) |
| model | TEXT | Model |
| status | TEXT | pending/analyzing/completed/failed |
| progress | INTEGER | İlerleme (0-100) |
| fingerprint_hash | TEXT | Parmak izi |

#### catalog_rules
| Kolon | Tip | Açıklama |
|-------|-----|----------|
| id | INTEGER PRIMARY KEY | Benzersiz ID |
| catalog_id | INTEGER FK | Katalog |
| rule_type | TEXT | toc/table/layout/structure |
| rules_json | TEXT | JSON formatında kurallar |
| copied_from | INTEGER FK | Kopyalandığı katalog |

#### catalog_categories
| Kolon | Tip | Açıklama |
|-------|-----|----------|
| id | INTEGER PRIMARY KEY | Benzersiz ID |
| catalog_id | INTEGER FK | Katalog |
| parent_id | INTEGER FK | Üst kategori (hiyerarşi) |
| title | TEXT | Kategori başlığı |
| page_start | INTEGER | Başlangıç sayfası |
| page_end | INTEGER | Bitiş sayfası |
| level | INTEGER | Hiyerarşi seviyesi |

#### catalog_parts
| Kolon | Tip | Açıklama |
|-------|-----|----------|
| id | INTEGER PRIMARY KEY | Benzersiz ID |
| catalog_id | INTEGER FK | Katalog |
| category_id | INTEGER FK | Kategori |
| page_number | INTEGER | Sayfa numarası |
| item_number | INTEGER | Sıra no |
| part_no | TEXT | Parça numarası |
| description | TEXT | Açıklama |
| qty | INTEGER | Miktar |
| remarks | TEXT | Notlar |

#### catalog_fingerprints
| Kolon | Tip | Açıklama |
|-------|-----|----------|
| id | INTEGER PRIMARY KEY | Benzersiz ID |
| catalog_id | INTEGER FK | Katalog |
| fingerprint_type | TEXT | Parmak izi tipi |
| fingerprint_value | TEXT | Parmak izi değeri |

### 4.4 Arama ve Önbellek Tabloları

#### search_cache
| Kolon | Tip | Açıklama |
|-------|-----|----------|
| id | INTEGER PRIMARY KEY | Benzersiz ID |
| cache_key | TEXT UNIQUE | Önbellek anahtarı |
| query | TEXT | Arama sorgusu |
| doc_type | TEXT | Döküman tipi |
| engines | TEXT | Kullanılan motorlar |
| results_json | TEXT | Sonuçlar (JSON) |
| expires_at | DATETIME | Son kullanma (10 yıl) |

#### search_logs
| Kolon | Tip | Açıklama |
|-------|-----|----------|
| id | INTEGER PRIMARY KEY | Benzersiz ID |
| user_id | INTEGER FK | Kullanıcı (NULL=guest) |
| query | TEXT | Arama sorgusu |
| doc_type | TEXT | Döküman tipi |
| engines_used | TEXT | Kullanılan motorlar (JSON) |
| result_count | INTEGER | Sonuç sayısı |
| credits_used | INTEGER | Harcanan kredi |
| is_cached | BOOLEAN | Önbellekten mi |

---

## 5. PDF Katalog Analiz Sistemi

### 5.1 Akış Diyagramı

```
                    ┌─────────────────┐
                    │  PDF Yükle      │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Parmak İzi      │
                    │ Kontrolü        │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
    ┌─────────────────┐           ┌─────────────────┐
    │ Benzer Katalog  │           │ Yeni Katalog    │
    │ Bulundu         │           │ (Claude Vision) │
    └────────┬────────┘           └────────┬────────┘
             │                             │
             │                             ▼
             │                    ┌─────────────────┐
             │                    │ İlk 30 Sayfayı  │
             │                    │ Analiz Et       │
             │                    └────────┬────────┘
             │                             │
             │         ┌───────────────────┼───────────────────┐
             │         │                   │                   │
             │         ▼                   ▼                   ▼
             │  ┌────────────┐      ┌────────────┐      ┌────────────┐
             │  │ TOC        │      │ Tablo      │      │ Layout     │
             │  │ Hiyerarşisi│      │ Yapısı     │      │ Kuralları  │
             │  └─────┬──────┘      └─────┬──────┘      └─────┬──────┘
             │        │                   │                   │
             │        └───────────────────┼───────────────────┘
             │                            │
             ▼                            ▼
    ┌─────────────────┐           ┌─────────────────┐
    │ Kuralları       │           │ Kuralları       │
    │ Kopyala         │           │ Kaydet          │
    └────────┬────────┘           └────────┬────────┘
             │                             │
             └──────────────┬──────────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │ Tüm Sayfaları   │
                   │ İşle (PyMuPDF)  │
                   └────────┬────────┘
                            │
              ┌─────────────┴─────────────┐
              │                           │
              ▼                           ▼
    ┌─────────────────┐         ┌─────────────────┐
    │ Kategorileri    │         │ Parçaları       │
    │ Çıkar           │         │ Çıkar           │
    └────────┬────────┘         └────────┬────────┘
             │                           │
             └─────────────┬─────────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ Sonuçları       │
                  │ Görüntüle       │
                  └─────────────────┘
```

### 5.2 Claude Vision Kullanımı

Sistem, katalog yapısını öğrenmek için Claude Vision API'sini kullanır:

1. **İlk Analiz**: PDF'in ilk 30 sayfası Claude Vision'a gönderilir
2. **Öğrenilen Bilgiler**:
   - TOC (İçindekiler) hiyerarşisi
   - Tablo yapısı (kolon sırası, başlıklar)
   - Layout kuralları (resim-tablo konumu)
   - Marka ve model bilgisi
3. **Parmak İzi**: Benzer kataloglar için kurallar yeniden kullanılır

### 5.3 Maliyet Optimizasyonu

| İşlem | Maliyet |
|-------|---------|
| İlk katalog analizi | ~20 kredi (~$0.20) |
| Benzer katalog (parmak izi eşleşmesi) | 0 kredi |
| Sayfa işleme (PyMuPDF) | 0 kredi |

---

## 6. API Endpoint'leri

### 6.1 Kimlik Doğrulama

| Endpoint | Metod | Açıklama |
|----------|-------|----------|
| `/api/auth/register` | POST | Kullanıcı kaydı |
| `/api/auth/login` | POST | Giriş (JWT token döner) |
| `/api/auth/me` | GET | Mevcut kullanıcı bilgisi |
| `/api/auth/forgot-password` | POST | Şifre sıfırlama |

### 6.2 Arama

| Endpoint | Metod | Açıklama |
|----------|-------|----------|
| `/api/search` | POST | PDF arama |
| `/api/scan-source` | POST | Kaynak tarama |
| `/cache/stats` | GET | Önbellek istatistikleri |

### 6.3 Katalog Yönetimi

| Endpoint | Metod | Açıklama |
|----------|-------|----------|
| `/api/catalogs/upload` | POST | PDF yükle |
| `/api/catalogs` | GET | Kullanıcının katalogları |
| `/api/catalogs/{id}` | GET | Katalog detayı |
| `/api/catalogs/{id}/toc` | GET | Kategori ağacı |
| `/api/catalogs/{id}/pages/{n}/image` | GET | Sayfa görseli |
| `/api/catalogs/{id}/pages/{n}/parts` | GET | Parça listesi |
| `/api/catalogs/{id}/progress` | GET | SSE ilerleme |

### 6.4 Kredi Sistemi

| Endpoint | Metod | Açıklama |
|----------|-------|----------|
| `/api/credit-requests` | POST | Kredi talebi oluştur |
| `/api/credit-requests/my` | GET | Kullanıcının talepleri |

### 6.5 Admin

| Endpoint | Metod | Açıklama |
|----------|-------|----------|
| `/api/admin/dashboard` | GET | İstatistikler |
| `/api/admin/users` | GET | Kullanıcı listesi |
| `/api/admin/credit-requests` | GET | Kredi talepleri |
| `/api/admin/credit-requests/{id}` | POST | Onayla/Reddet |
| `/api/admin/settings` | GET/PUT | Ayarlar |
| `/api/admin/search-logs` | GET | Arama logları |

---

## 7. Güvenlik

### 7.1 API Anahtarları

- Veritabanında **Fernet şifrelemesi** ile saklanır
- Şifreleme anahtarı `.env` dosyasında tutulur
- Admin panelinden yönetilebilir

### 7.2 Kullanıcı Şifreleri

- **bcrypt** ile hash'lenir
- Salt otomatik oluşturulur

### 7.3 JWT Token

- 24 saat geçerlilik
- Kullanıcı ID, e-posta, tier ve rol içerir

---

## 8. Kullanıcı Tier'ları

| Tier | Özellikler |
|------|------------|
| **Guest** | Arama yapabilir, indirme kilitli |
| **Free** | 5 arama/gün, 50 başlangıç kredisi |
| **Pro** | Sınırsız arama, kredi bazlı |
| **Enterprise** | Sınırsız, API erişimi |

### Kredi Maliyetleri

| İşlem | Maliyet |
|-------|---------|
| Önbellekten sonuç | 1 kredi |
| API araması (motor başına) | 10-15 kredi |
| Katalog analizi | 20 kredi |

---

## 9. Frontend Sayfaları

| Sayfa | URL | Açıklama |
|-------|-----|----------|
| Ana Sayfa | `/` | Landing page |
| Giriş | `/login.html` | Kullanıcı girişi |
| Kayıt | `/register.html` | Yeni kayıt |
| Arama | `/search.html` | PDF arama |
| Panel | `/dashboard.html` | Kullanıcı paneli |
| Katalog | `/catalog-viewer.html` | PDF görüntüleyici |
| Admin | `/admin` | Admin paneli |

---

## 10. Tasarım

- **Tema**: Endüstriyel / MakineParça
- **Ana Renk**: Sarı (#ffc300)
- **Arka Plan**: Koyu (#1a1a1a)
- **Font**: Inter
- **İkonlar**: Material Symbols
- **Efektler**: Hazard stripe, industrial corner

---

## 11. Kurulum

### Gereksinimler

- Python 3.11+
- pip

### Adımlar

```bash
# 1. Bağımlılıkları yükle
pip install -r requirements.txt

# 2. .env dosyasını oluştur
cp .env.example .env
# ANTHROPIC_API_KEY ve ENCRYPTION_KEY ekle

# 3. Veritabanını başlat
python -c "from src.database import PEPCDatabase; PEPCDatabase().init_database()"

# 4. Admin hesabı oluştur
python create_admin.py

# 5. Sunucuyu başlat
python -m uvicorn api.main:app --host 0.0.0.0 --port 8001 --reload
```

### Erişim

- **Uygulama**: http://localhost:8001
- **Admin Panel**: http://localhost:8001/admin
- **API Docs**: http://localhost:8001/docs

---

## 12. Ortam Değişkenleri (.env)

```env
# Claude Vision API (zorunlu)
ANTHROPIC_API_KEY=sk-ant-...

# JWT için gizli anahtar
JWT_SECRET_KEY=your-secret-key

# API anahtarları şifreleme anahtarı (otomatik oluşturulur)
ENCRYPTION_KEY=...
```

---

## 13. Lisans

Bu proje özel kullanım içindir.

---

*Son güncelleme: Aralık 2025*


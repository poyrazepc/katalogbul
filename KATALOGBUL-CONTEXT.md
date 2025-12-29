# KatalogBul Proje Bağlamı

## Proje Özeti
KatalogBul (MakineParca) - B2B SaaS platformu, ağır makine parça kataloglarını bulmak için.

## Teknoloji Stack
- **Backend:** FastAPI + Uvicorn
- **Database:** SQLite (`data/pepc.db`)
- **Frontend:** Vanilla HTML/CSS/JS (`frontend/` klasörü)
- **Auth:** JWT + passlib (pbkdf2_sha256)
- **Search APIs:** Serper, Brave, Firecrawl (Yandex opsiyonel)

## Dosya Yapısı
```
katalogbul/
├── api/
│   └── main.py          # FastAPI ana uygulama (2869 satır)
├── src/
│   ├── auth.py          # JWT authentication
│   ├── config.py        # Konfigürasyon
│   ├── database.py      # SQLite işlemleri
│   ├── multi_search.py  # Çoklu arama motoru
│   └── models.py        # Pydantic modeller
├── frontend/
│   ├── index.html       # Ana sayfa
│   ├── login.html       # Giriş
│   ├── register.html    # Kayıt
│   ├── search.html      # Arama
│   ├── dashboard.html   # Kullanıcı paneli
│   └── admin.html       # Admin paneli
├── data/
│   └── pepc.db          # SQLite veritabanı
├── requirements.txt     # Python bağımlılıkları
├── Procfile            # Railway için
└── railway.toml        # Railway konfigürasyonu
```

## Railway Deployment
- **URL:** https://web-production-19720.up.railway.app
- **Project ID:** 3c461da1-c1a0-4201-8f95-12af4f1b55b5
- **Plan:** Hobby ($5/month)
- **Region:** EU West (Amsterdam)

### Environment Variables (Railway'de tanımlı)
```
DATABASE_PATH=data/pepc.db
JWT_SECRET_KEY=katalogbul-secret-key-change-in-production-2025
ENCRYPTION_KEY=Xa5DVkh6FrgRoPd47LbAzIEFPIbdPgLXr59fFde-es8=
ANTHROPIC_API_KEY=sk-ant-api03-...
SERPER_API_KEY=b157d885993f39309eb57566743436abdcf0d4a4
BRAVE_API_KEY=BSAXZzD8q7BZ4FLM3hOoUU4hLJkd8n8
FIRECRAWL_API_KEY=fc-19d244b778054145bf8c7b9f5ff967ae
```

## Önemli Sayfalar
| Sayfa | URL |
|-------|-----|
| Ana Sayfa | / |
| Giriş | /login.html |
| Kayıt | /register.html |
| Arama | /search.html |
| Dashboard | /dashboard.html |
| Admin Panel | /admin |

## Test Kullanıcısı
- **Email:** admin@test.com
- **Şifre:** Hopd445566++
- **Rol:** admin
- **Tier:** enterprise

## Veritabanı Tabloları
- `users` - Kullanıcılar
- `search_cache` - Arama önbelleği
- `search_logs` - Arama logları
- `pdf_catalog` - PDF katalogları
- `pdf_sources` - PDF kaynakları
- `payments` - Ödemeler
- `settings` - Sistem ayarları
- `favorites` - Favoriler

## Geliştirme Workflow
1. `katalogbul/` klasöründe düzenleme yap
2. GitHub Desktop ile commit + push
3. Railway otomatik deploy eder (~2-3 dakika)

## SSH Bağlantısı (Debug için)
```powershell
railway ssh --project=3c461da1-c1a0-4201-8f95-12af4f1b55b5 --environment=e1df60e9-fff6-488f-931e-f0fa642f24dd --service=c7212b8a-95f6-4fa3-86d8-37fad44aa662
```

## Bilinen Sorunlar & Çözümler

### 1. Bcrypt Hatası
**Sorun:** `password cannot be longer than 72 bytes`
**Çözüm:** `auth.py`'de `bcrypt` yerine `pbkdf2_sha256` kullanılıyor

### 2. Volume Yok
**Durum:** Şu an volume bağlı değil
**Etki:** Her deploy'da veritabanı GitHub'daki haline dönüyor
**Çözüm:** Production için Volume ekle (`/app/data`)

### 3. Yandex Client
**Durum:** `authorized_key.json` yok
**Çözüm:** `multi_search.py`'de try-except ile opsiyonel yapıldı

## Lokal Geliştirme
```powershell
cd C:\xampp\htdocs\pdfbulma
python -m uvicorn api.main:app --reload --port 8000
```

## API Endpoints (Önemli)
- `POST /api/auth/login` - Giriş
- `POST /api/auth/register` - Kayıt
- `GET /api/auth/me` - Kullanıcı bilgisi
- `POST /api/search` - Arama
- `GET /api/admin/dashboard` - Admin dashboard
- `GET /api/admin/users` - Kullanıcı listesi

## Notlar
- GitHub repo: poyrazepc/katalogbul (public)
- Password hashing: pbkdf2_sha256 (bcrypt değil!)
- Frontend: /static altında serve ediliyor
- Healthcheck: / endpoint'i

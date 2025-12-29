# PDFARA / KatalogBul - Görev Listesi

## ✅ Tamamlanan Düzeltmeler (28 Aralık 2024)

### 🔧 Arama Sistemi Hataları
1. **Yandex Çift Filtre Sorunu** ✅
   - Query builder `filetype:pdf` ekliyor
   - Yandex client tekrar `mime:pdf` ekliyordu → Düzeltildi
   - Dosya: `src/yandex_client.py`

2. **PDF Kontrolü Çok Kısıtlayıcı** ✅
   - Sadece URL'de `.pdf` aranıyordu
   - Artık title ve description'da da aranıyor
   - Dosyalar: `src/serper_client.py`, `src/brave_client.py`, `src/search/google.py`, `src/search/brave.py`

3. **Brave Pagination Limiti** ✅
   - `offset < 100` → `offset < 200` (10 sayfa)
   - Dosyalar: `src/brave_client.py`, `src/search/brave.py`

4. **Brave Client Çift filetype:pdf** ✅
   - Query zaten içeriyorsa tekrar eklemiyor
   - Dosya: `src/brave_client.py`

### 🆕 Kaynak Keşif Sistemi (Source Discovery)
5. **Firecrawl /map Entegrasyonu** ✅
   - Arama sonuçlarından benzersiz domain çıkarma
   - Her domain için path tabanlı tarama
   - SSE ile gerçek zamanlı progress
   - HTTP HEAD ile paralel boyut kontrolü (50 concurrent)
   - Dosya: `src/source_discovery.py` (YENİ)

6. **Yeni API Endpoint'leri** ✅
   - `POST /api/sources/extract` - Sonuçlardan kaynak çıkar
   - `GET /api/sources/{domain}/scan` - SSE ile kaynak tara
   - `POST /api/sources/scan` - Senkron kaynak tarama
   - `POST /api/sources/scan-multiple` - Toplu tarama
   - `POST /api/sources/filter-by-size` - Boyut filtresi
   - Dosya: `api/main.py`

7. **Frontend - Yeni Tab'lar** ✅
   - "Kaynaklar" tab'ı - Benzersiz domainler, Tara butonu
   - "Kaynak Sonuçları" tab'ı - Bulunan PDF'ler, boyut filtresi
   - Progress bar ile gerçek zamanlı takip
   - Dosya: `frontend/search.html`

### 📁 Proje Yapılandırması
8. **.cursorignore Oluşturuldu** ✅
   - Hassas dosyalar koruma altında
   - `.env`, `authorized_key.json`, `*.db`, `*.log` vb.

9. **Kural Dosyaları Güncellendi** ✅
   - `.cursor/rules/project.mdc`
   - `.cursor/rules/python.mdc`
   - `.cursor/rules/api.mdc`

---

## 🔄 Aktif Özellikler

### Arama Motorları
| Motor | Durum | API |
|-------|-------|-----|
| Google (Serper) | ✅ Aktif | serper.dev |
| Brave Search | ✅ Aktif | api.search.brave.com |
| Yandex | ✅ Aktif | searchapi.api.cloud.yandex.net |
| SearchApi (Bing) | ✅ Aktif | searchapi.io |
| Firecrawl | ✅ Aktif | api.firecrawl.dev |

### Kaynak Keşif Akışı
```
┌─────────────────────────────────────────────────────────────────┐
│                    KULLANICI ARAMA YAPAR                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
        ┌───────────────────┴───────────────────┐
        ▼                                       ▼
┌──────────────────┐                  ┌─────────────────────────┐
│ Ana Arama        │                  │ Kaynak Çıkarma          │
│ Serper/Brave     │                  │ (Benzersiz domainler)   │
└────────┬─────────┘                  └───────────┬─────────────┘
         │                                        │
         ▼                                        ▼
   [Tümü/Ücretsiz/Premium]              [Kaynaklar Tab'ı]
         Tab'ları                        Domain listesi
                                         + Tara butonları
                                                │
                                                ▼
                                   ┌─────────────────────────┐
                                   │ Firecrawl /map          │
                                   │ (1 kredi / tarama)      │
                                   └───────────┬─────────────┘
                                               │
                                               ▼
                                   ┌─────────────────────────┐
                                   │ HTTP HEAD (paralel)     │
                                   │ Boyut kontrolü          │
                                   └───────────┬─────────────┘
                                               │
                                               ▼
                                   [Kaynak Sonuçları Tab'ı]
                                    PDF listesi + boyut filtre
```

### Firecrawl Kullanımı
- **Ana Dosya**: `src/source_discovery.py`
- **Maliyet**: 1 kredi = 1 /map çağrısı (max 5000 URL)
- **HTTP HEAD**: Ücretsiz (kendi sunucudan)

---

## 📋 Yapılacaklar (TODO)

### Yüksek Öncelik
- [ ] Cache temizleme mekanizması (eski sonuçları kaldır)
- [ ] API key geçerlilik kontrolü
- [ ] Rate limiting iyileştirme

### Orta Öncelik
- [ ] Arama sonuçları için relevance scoring
- [ ] Daha fazla marka alias'ı ekleme
- [ ] Kaynak tarama sonuçlarını DB'ye kaydet

### Düşük Öncelik
- [ ] SearchApi Baidu/Naver entegrasyonu test
- [ ] Premium site listesi genişletme
- [ ] Batch arama özelliği

---

## 🗂️ Dosya Yapısı

```
pdfara/
├── api/
│   └── main.py              # FastAPI endpoint'leri (+kaynak keşif)
├── src/
│   ├── source_discovery.py  # 🆕 Firecrawl /map entegrasyonu
│   ├── search/              # Arama modülleri
│   ├── data/               # Veri tanımları
│   ├── pdf/
│   │   └── head_checker.py  # Paralel HTTP HEAD (50 concurrent)
│   ├── serper_client.py
│   ├── brave_client.py
│   ├── yandex_client.py
│   ├── searchapi_client.py
│   ├── firecrawl_google_scraper.py
│   ├── multi_search.py
│   ├── source_scanner.py
│   └── ...
├── frontend/
│   └── search.html          # 5 tab: Tümü/Ücretsiz/Premium/Kaynaklar/Kaynak Sonuçları
├── .cursor/rules/
├── .cursorignore
├── .env                     # (GİZLİ)
└── authorized_key.json      # (GİZLİ)
```

---

## 🔐 Güvenlik Notları

### .cursorignore ile Korunan
- `.env` - Tüm API key'ler
- `authorized_key.json` - Yandex service account
- `*.db` - Veritabanları
- `*.log` - Log dosyaları
- `uploads/`, `thumbnails/` - Kullanıcı dosyaları

---

*Son Güncelleme: 28 Aralık 2024*

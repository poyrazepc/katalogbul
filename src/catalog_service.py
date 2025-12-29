"""
Katalog Öğrenme Servisi
PDF katalog yükleme, analiz etme ve parse etme işlemleri
"""
import os
import json
import uuid
import base64
import asyncio
import logging
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Generator

from dotenv import load_dotenv
import fitz  # PyMuPDF
import anthropic

# .env dosyasını yükle
load_dotenv(Path(__file__).parent.parent / ".env")

from src.config import DATABASE_PATH

# Logging
logger = logging.getLogger(__name__)

# Uploads dizini
UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


class CatalogService:
    """Katalog yükleme ve analiz servisi"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DATABASE_PATH
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.claude_model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
        
        if self.anthropic_key:
            self.client = anthropic.Anthropic(api_key=self.anthropic_key)
        else:
            self.client = None
            logger.warning("[CatalogService] ANTHROPIC_API_KEY ayarlanmamış!")
    
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    # ============================================
    # YÜKLEME
    # ============================================
    
    def upload_catalog(self, user_id: int, file_bytes: bytes, original_name: str) -> Dict:
        """
        PDF dosyasını yükle ve veritabanına kaydet
        
        Returns:
            {"id": catalog_id, "filename": "...", "status": "pending"}
        """
        # Unique dosya adı oluştur
        file_ext = Path(original_name).suffix or ".pdf"
        unique_name = f"{uuid.uuid4().hex}{file_ext}"
        file_path = UPLOADS_DIR / unique_name
        
        # Dosyayı kaydet
        with open(file_path, "wb") as f:
            f.write(file_bytes)
        
        # PDF bilgilerini al
        doc = fitz.open(str(file_path))
        total_pages = doc.page_count
        file_size = len(file_bytes)
        doc.close()
        
        # Veritabanına kaydet
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO user_catalogs 
                (user_id, filename, original_name, file_path, file_size, total_pages, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """, (user_id, unique_name, original_name, str(file_path), file_size, total_pages))
            
            catalog_id = cursor.lastrowid
            conn.commit()
            
            return {
                "id": catalog_id,
                "filename": unique_name,
                "original_name": original_name,
                "total_pages": total_pages,
                "file_size": file_size,
                "status": "pending"
            }
        finally:
            conn.close()
    
    def update_progress(self, catalog_id: int, progress: int, message: str, status: str = None):
        """İlerleme durumunu güncelle"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            if status:
                cursor.execute("""
                    UPDATE user_catalogs 
                    SET progress = ?, progress_message = ?, status = ?
                    WHERE id = ?
                """, (progress, message, status, catalog_id))
            else:
                cursor.execute("""
                    UPDATE user_catalogs 
                    SET progress = ?, progress_message = ?
                    WHERE id = ?
                """, (progress, message, catalog_id))
            
            # İlerleme log'u ekle
            cursor.execute("""
                INSERT INTO catalog_analysis_progress (catalog_id, step, progress, message)
                VALUES (?, ?, ?, ?)
            """, (catalog_id, status or 'progress', progress, message))
            
            conn.commit()
        finally:
            conn.close()
    
    def get_progress(self, catalog_id: int) -> Dict:
        """Katalog ilerleme durumunu al"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT status, progress, progress_message, error_message
                FROM user_catalogs WHERE id = ?
            """, (catalog_id,))
            
            row = cursor.fetchone()
            if row:
                return {
                    "status": row["status"],
                    "progress": row["progress"],
                    "message": row["progress_message"],
                    "error": row["error_message"]
                }
            return None
        finally:
            conn.close()
    
    # ============================================
    # CLAUDE VISION ANALİZİ
    # ============================================
    
    FULL_ANALYSIS_PROMPT = """Bu bir ağır makine parça kataloğunun sayfaları.

Tüm yapıyı analiz et ve şunları çıkar:

1. KATALOG YAPISI
   - Hangi sayfalar kapak?
   - Hangi sayfalar içindekiler (TOC)?
   - Hangi sayfalar giriş/açıklama?
   - İlk parça sayfası hangisi?
   - Alfabetik index var mı, hangi sayfada başlıyor?

2. TOC HİYERARŞİSİ (İçindekiler sayfalarından)
   - Ana kategoriler
   - Alt kategoriler
   - Her birinin sayfa numarası
   - Hiyerarşi seviyeleri

3. PARÇA SAYFASI LAYOUT'U
   - Patlamış resim ve tablo AYNI SAYFADA MI, AYRI SAYFALARDA MI?
   - Ayrı sayfalardaysa: Önce resim mi, önce tablo mu?
   - Aynı sayfadaysa: Resim ÜSTTE mi ALTTA mı? Tablo ÜSTTE mi ALTTA mı?

4. TABLO YAPISI (Parça tablosu sayfalarından)
   - Kolon başlıkları (soldan sağa sırayla)
   - Her kolonun tipi (item, part_no, description, qty, remarks)
   - Part number formatı (örnek ver)

5. MARKA/MODEL
   - Marka adı
   - Model numarası
   - Katalog tipi

JSON formatında yanıt ver:
{
  "structure": {
    "cover_pages": [0, 1, 2],
    "toc_pages": [3, 4, 5, 6, 7, 8],
    "intro_pages": [9],
    "first_parts_page": 10,
    "index_start_page": null,
    "total_pages_analyzed": 30
  },
  "toc_hierarchy": [
    {
      "level": 0,
      "title": "Electric system",
      "page": 45,
      "children": [
        {"level": 1, "title": "Battery", "page": 46}
      ]
    }
  ],
  "layout": {
    "image_table_same_page": false,
    "image_first": true,
    "table_position": "full_page",
    "image_position": "full_page",
    "notes": "Resim ve tablo ayrı sayfalarda"
  },
  "table_structure": {
    "columns": [
      {"index": 0, "name": "Item", "type": "item"},
      {"index": 1, "name": "Part No.", "type": "part_no"},
      {"index": 2, "name": "Description", "type": "description"},
      {"index": 3, "name": "Qty", "type": "qty"},
      {"index": 4, "name": "Remarks", "type": "remarks"}
    ],
    "part_number_format": "10 haneli sayı",
    "part_number_example": "4812158581"
  },
  "catalog_info": {
    "brand": "Dynapac",
    "model": "CA2500D",
    "type": "Parts Manual",
    "language": "English"
  }
}"""

    async def analyze_catalog(self, catalog_id: int) -> Dict:
        """
        Katalog yapısını Claude Vision ile analiz et (async)
        
        Bu fonksiyon arka planda çalışır ve ilerleme güncellemeleri yapar
        """
        logger.info(f"[CatalogService] Analiz başlatıldı: catalog_id={catalog_id}")
        
        if not self.client:
            self.update_progress(catalog_id, 0, "API key bulunamadı", "failed")
            return {"success": False, "error": "ANTHROPIC_API_KEY ayarlanmamış"}
        
        # Katalog bilgilerini al
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_catalogs WHERE id = ?", (catalog_id,))
        catalog = cursor.fetchone()
        conn.close()
        
        if not catalog:
            return {"success": False, "error": "Katalog bulunamadı"}
        
        file_path = catalog["file_path"]
        
        try:
            # Durum: Analiz başladı
            self.update_progress(catalog_id, 5, "PDF okunuyor...", "analyzing")
            
            # PDF'i aç
            doc = fitz.open(file_path)
            total_pages = doc.page_count
            max_pages = min(30, total_pages)  # Maliyet optimizasyonu
            
            self.update_progress(catalog_id, 10, f"{max_pages} sayfa hazırlanıyor...")
            
            # Görselleri hazırla
            content = []
            content.append({
                "type": "text",
                "text": f"Bu katalog toplam {total_pages} sayfa. İlk {max_pages} sayfayı analiz ediyorum:"
            })
            
            for page_num in range(max_pages):
                page = doc[page_num]
                pix = page.get_pixmap(dpi=100)
                img_bytes = pix.tobytes("png")
                img_base64 = base64.standard_b64encode(img_bytes).decode("utf-8")
                
                content.append({
                    "type": "text",
                    "text": f"\n--- Sayfa {page_num + 1} ---"
                })
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_base64
                    }
                })
                
                # İlerleme güncelle
                progress = 10 + int((page_num / max_pages) * 30)
                self.update_progress(catalog_id, progress, f"Sayfa {page_num + 1}/{max_pages} hazırlandı...")
            
            doc.close()
            
            # Ana prompt ekle
            content.append({
                "type": "text",
                "text": self.FULL_ANALYSIS_PROMPT
            })
            
            self.update_progress(catalog_id, 45, "Claude Vision analiz ediyor...")
            
            # Claude API çağrısı
            response = self.client.messages.create(
                model=self.claude_model,
                max_tokens=4000,
                messages=[{"role": "user", "content": content}]
            )
            
            raw_text = response.content[0].text
            tokens_used = response.usage.input_tokens + response.usage.output_tokens
            
            self.update_progress(catalog_id, 70, "Sonuçlar işleniyor...")
            
            # JSON parse et
            result = self._extract_json(raw_text)
            
            if not result:
                self.update_progress(catalog_id, 0, "JSON parse hatası", "failed")
                return {"success": False, "error": "JSON parse edilemedi"}
            
            # Kuralları kaydet
            self.update_progress(catalog_id, 80, "Kurallar kaydediliyor...")
            await self._save_analysis_results(catalog_id, result)
            
            # Katalog bilgilerini güncelle
            catalog_info = result.get("catalog_info", {})
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_catalogs 
                SET brand = ?, model = ?, catalog_type = ?, 
                    status = 'completed', progress = 100, 
                    progress_message = 'Analiz tamamlandı',
                    analyzed_at = ?
                WHERE id = ?
            """, (
                catalog_info.get("brand"),
                catalog_info.get("model"),
                catalog_info.get("type"),
                datetime.now().isoformat(),
                catalog_id
            ))
            conn.commit()
            conn.close()
            
            self.update_progress(catalog_id, 100, "Analiz tamamlandı!", "completed")
            
            return {
                "success": True,
                "tokens_used": tokens_used,
                "result": result
            }
            
        except Exception as e:
            logger.error(f"[CatalogService] Analiz hatası: {e}")
            self.update_progress(catalog_id, 0, str(e), "failed")
            
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_catalogs SET error_message = ? WHERE id = ?
            """, (str(e), catalog_id))
            conn.commit()
            conn.close()
            
            return {"success": False, "error": str(e)}
    
    async def _save_analysis_results(self, catalog_id: int, result: Dict):
        """Analiz sonuçlarını veritabanına kaydet"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Structure kuralı
            if "structure" in result:
                cursor.execute("""
                    INSERT INTO catalog_rules (catalog_id, rule_type, rules_json)
                    VALUES (?, 'structure', ?)
                    ON CONFLICT(catalog_id, rule_type) DO UPDATE SET
                        rules_json = ?, updated_at = CURRENT_TIMESTAMP
                """, (catalog_id, json.dumps(result["structure"]), json.dumps(result["structure"])))
            
            # TOC hierarchy'den kategorileri kaydet
            if "toc_hierarchy" in result:
                cursor.execute("""
                    INSERT INTO catalog_rules (catalog_id, rule_type, rules_json)
                    VALUES (?, 'toc', ?)
                    ON CONFLICT(catalog_id, rule_type) DO UPDATE SET
                        rules_json = ?, updated_at = CURRENT_TIMESTAMP
                """, (catalog_id, json.dumps(result["toc_hierarchy"]), json.dumps(result["toc_hierarchy"])))
                
                # Kategorileri ayrıca kaydet
                self._save_categories(cursor, catalog_id, result["toc_hierarchy"])
            
            # Layout kuralı
            if "layout" in result:
                cursor.execute("""
                    INSERT INTO catalog_rules (catalog_id, rule_type, rules_json)
                    VALUES (?, 'layout', ?)
                    ON CONFLICT(catalog_id, rule_type) DO UPDATE SET
                        rules_json = ?, updated_at = CURRENT_TIMESTAMP
                """, (catalog_id, json.dumps(result["layout"]), json.dumps(result["layout"])))
            
            # Table structure kuralı
            if "table_structure" in result:
                cursor.execute("""
                    INSERT INTO catalog_rules (catalog_id, rule_type, rules_json)
                    VALUES (?, 'table', ?)
                    ON CONFLICT(catalog_id, rule_type) DO UPDATE SET
                        rules_json = ?, updated_at = CURRENT_TIMESTAMP
                """, (catalog_id, json.dumps(result["table_structure"]), json.dumps(result["table_structure"])))
            
            conn.commit()
        finally:
            conn.close()
    
    def _save_categories(self, cursor, catalog_id: int, hierarchy: List[Dict], parent_id: int = None, sort_order: int = 0):
        """Kategorileri recursive olarak kaydet"""
        for i, item in enumerate(hierarchy):
            cursor.execute("""
                INSERT INTO catalog_categories 
                (catalog_id, parent_id, title, page_start, level, sort_order)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                catalog_id,
                parent_id,
                item.get("title", ""),
                item.get("page"),
                item.get("level", 0),
                sort_order + i
            ))
            
            cat_id = cursor.lastrowid
            
            # Alt kategorileri kaydet
            children = item.get("children", [])
            if children:
                self._save_categories(cursor, catalog_id, children, cat_id, 0)
    
    def _extract_json(self, text: str) -> Dict:
        """Yanıttan JSON çıkar"""
        try:
            start = text.find('{')
            end = text.rfind('}') + 1
            
            if start >= 0 and end > start:
                json_str = text[start:end]
                return json.loads(json_str)
        except Exception as e:
            logger.error(f"[CatalogService] JSON parse hatası: {e}")
        
        return {}
    
    # ============================================
    # KATALOG LİSTELEME
    # ============================================
    
    def get_user_catalogs(self, user_id: int, page: int = 1, per_page: int = 20) -> Dict:
        """Kullanıcının kataloglarını listele"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Toplam sayı
            cursor.execute("""
                SELECT COUNT(*) FROM user_catalogs WHERE user_id = ?
            """, (user_id,))
            total = cursor.fetchone()[0]
            
            # Kataloglar
            cursor.execute("""
                SELECT id, filename, original_name, file_size, total_pages,
                       brand, model, catalog_type, status, progress, progress_message,
                       created_at, analyzed_at, last_viewed
                FROM user_catalogs
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (user_id, per_page, (page - 1) * per_page))
            
            catalogs = [dict(row) for row in cursor.fetchall()]
            
            return {
                "items": catalogs,
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page
            }
        finally:
            conn.close()
    
    def get_catalog_by_id(self, catalog_id: int, user_id: int = None) -> Optional[Dict]:
        """Katalog detayını al"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            if user_id:
                cursor.execute("""
                    SELECT * FROM user_catalogs WHERE id = ? AND user_id = ?
                """, (catalog_id, user_id))
            else:
                cursor.execute("SELECT * FROM user_catalogs WHERE id = ?", (catalog_id,))
            
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    # ============================================
    # TOC VE PARÇA PARSE
    # ============================================
    
    def get_catalog_toc(self, catalog_id: int) -> List[Dict]:
        """Katalog içindekiler listesini al"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Önce kaydedilmiş kategorileri kontrol et
            cursor.execute("""
                SELECT id, parent_id, title, page_start, level, sort_order
                FROM catalog_categories
                WHERE catalog_id = ?
                ORDER BY sort_order, page_start
            """, (catalog_id,))
            
            rows = cursor.fetchall()
            
            if not rows:
                return []
            
            # Hiyerarşik yapıya dönüştür
            categories = {}
            root_items = []
            
            for row in rows:
                cat = {
                    "id": row["id"],
                    "title": row["title"],
                    "page": row["page_start"],
                    "level": row["level"],
                    "children": []
                }
                categories[row["id"]] = cat
                
                if row["parent_id"] is None:
                    root_items.append(cat)
                else:
                    parent = categories.get(row["parent_id"])
                    if parent:
                        parent["children"].append(cat)
            
            return root_items
        finally:
            conn.close()
    
    def get_page_image(self, catalog_id: int, page_num: int, dpi: int = 150) -> bytes:
        """Sayfa görselini al"""
        catalog = self.get_catalog_by_id(catalog_id)
        if not catalog:
            raise ValueError("Katalog bulunamadı")
        
        file_path = catalog["file_path"]
        
        doc = fitz.open(file_path)
        if page_num >= doc.page_count:
            doc.close()
            raise ValueError("Geçersiz sayfa numarası")
        
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")
        doc.close()
        
        return img_bytes
    
    def get_page_parts(self, catalog_id: int, page_num: int) -> List[Dict]:
        """Sayfa parça listesini al"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Önce veritabanından kontrol et
            cursor.execute("""
                SELECT item_number, part_no, description, qty, remarks
                FROM catalog_parts
                WHERE catalog_id = ? AND page_number = ?
                ORDER BY item_number
            """, (catalog_id, page_num))
            
            rows = cursor.fetchall()
            
            if rows:
                return [{
                    "item": row["item_number"],
                    "part_no": row["part_no"],
                    "description": row["description"],
                    "qty": row["qty"],
                    "l": row["remarks"] or ""
                } for row in rows]
            
            # Veritabanında yoksa kurallara göre parse et
            return self._parse_page_parts(catalog_id, page_num)
        finally:
            conn.close()
    
    def _parse_page_parts(self, catalog_id: int, page_num: int) -> List[Dict]:
        """Sayfadaki parçaları parse et"""
        catalog = self.get_catalog_by_id(catalog_id)
        if not catalog:
            return []
        
        # Kuralları al
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rule_type, rules_json FROM catalog_rules WHERE catalog_id = ?
        """, (catalog_id,))
        
        rules = {}
        for row in cursor.fetchall():
            rules[row["rule_type"]] = json.loads(row["rules_json"])
        conn.close()
        
        table_rules = rules.get("table", {})
        
        # PDF'den parse et
        file_path = catalog["file_path"]
        
        try:
            doc = fitz.open(file_path)
            if page_num >= doc.page_count:
                doc.close()
                return []
            
            page = doc[page_num]
            
            # PyMuPDF find_tables kullan
            parts = self._parse_with_pymupdf(page, table_rules, page_num)
            doc.close()
            
            return parts
        except Exception as e:
            logger.error(f"[CatalogService] Parse hatası: {e}")
            return []
    
    def _parse_with_pymupdf(self, page, table_rules: Dict, page_num: int) -> List[Dict]:
        """PyMuPDF find_tables ile parse et"""
        try:
            tables = page.find_tables()
            
            if not tables or len(tables.tables) == 0:
                return []
            
            table = tables.tables[0]
            rows = table.extract()
            
            if not rows:
                return []
            
            # Kolon mapping
            columns = table_rules.get("columns", [])
            col_map = {}
            
            for col in columns:
                col_type = col.get("type") or col.get("semantic_type", "")
                col_index = col.get("index", -1)
                col_name = col.get("name", "").lower()
                
                if col_type == "item" or "item" in col_name:
                    col_map["item"] = col_index
                elif col_type == "part_no" or "part" in col_name:
                    col_map["part_no"] = col_index
                elif col_type == "description" or "name" in col_name:
                    col_map["description"] = col_index
                elif col_type == "qty" or "qty" in col_name:
                    col_map["qty"] = col_index
                elif col_type == "remarks":
                    col_map["l"] = col_index
            
            # Default mapping
            if not col_map:
                col_map = {"item": 0, "part_no": 1, "description": 2, "qty": 3, "l": 4}
            
            parts = []
            start_row = 1 if len(rows) > 1 else 0
            
            for row in rows[start_row:]:
                if not row or all(cell is None or str(cell).strip() == "" for cell in row):
                    continue
                
                part = {
                    "item": None,
                    "part_no": "",
                    "description": "",
                    "qty": 1,
                    "l": ""
                }
                
                # Item
                if "item" in col_map and col_map["item"] < len(row):
                    val = row[col_map["item"]]
                    if val:
                        try:
                            part["item"] = int(str(val).strip())
                        except:
                            pass
                
                # Part No
                if "part_no" in col_map and col_map["part_no"] < len(row):
                    val = row[col_map["part_no"]]
                    if val:
                        part["part_no"] = str(val).strip()
                
                # Description
                if "description" in col_map and col_map["description"] < len(row):
                    val = row[col_map["description"]]
                    if val:
                        part["description"] = str(val).strip()
                
                # Qty
                if "qty" in col_map and col_map["qty"] < len(row):
                    val = row[col_map["qty"]]
                    if val:
                        try:
                            part["qty"] = int(str(val).strip())
                        except:
                            part["qty"] = 1
                
                # L/Remarks
                if "l" in col_map and col_map["l"] < len(row):
                    val = row[col_map["l"]]
                    if val:
                        part["l"] = str(val).strip()
                
                if part["part_no"]:
                    parts.append(part)
            
            return parts
            
        except Exception as e:
            logger.error(f"[CatalogService] PyMuPDF parse hatası: {e}")
            return []
    
    # ============================================
    # KREDİ KONTROLÜ
    # ============================================
    
    def check_analysis_credits(self, user_id: int) -> Dict:
        """
        Kullanıcının analiz yapabilmesi için yeterli kredisi var mı kontrol et
        
        Returns:
            {"allowed": True/False, "credits_needed": 20, "current_balance": X, "reason": "..."}
        """
        ANALYSIS_COST = 20  # Claude Vision API maliyeti
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT credit_balance, subscription_tier FROM users WHERE id = ?
            """, (user_id,))
            
            row = cursor.fetchone()
            if not row:
                return {"allowed": False, "reason": "Kullanıcı bulunamadı"}
            
            balance = row["credit_balance"]
            tier = row["subscription_tier"]
            
            # Enterprise kullanıcılar sınırsız
            if tier == "enterprise":
                return {"allowed": True, "credits_needed": 0, "current_balance": balance}
            
            # Kredi kontrolü
            if balance >= ANALYSIS_COST:
                return {
                    "allowed": True,
                    "credits_needed": ANALYSIS_COST,
                    "current_balance": balance
                }
            else:
                return {
                    "allowed": False,
                    "credits_needed": ANALYSIS_COST,
                    "current_balance": balance,
                    "reason": f"Yetersiz kredi. Gerekli: {ANALYSIS_COST}, Mevcut: {balance}"
                }
        finally:
            conn.close()
    
    def deduct_analysis_credits(self, user_id: int) -> bool:
        """Analiz kredisini düş"""
        ANALYSIS_COST = 20
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE users 
                SET credit_balance = credit_balance - ?
                WHERE id = ? AND credit_balance >= ?
            """, (ANALYSIS_COST, user_id, ANALYSIS_COST))
            
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


# Singleton instance
_catalog_service = None

def get_catalog_service() -> CatalogService:
    """CatalogService singleton instance'ı al"""
    global _catalog_service
    if _catalog_service is None:
        _catalog_service = CatalogService()
    return _catalog_service


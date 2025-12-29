"""
Parts Catalog Analyzer - PDF'den parça kataloğu çıkarma
"""
import re
from typing import List, Dict, Any
from pathlib import Path
import fitz  # PyMuPDF

class CatalogAnalyzer:
    """PDF parts catalog analyzer"""
    
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.total_pages = len(self.doc)
        
    def analyze_structure(self, toc_start=None, toc_end=None) -> Dict[str, Any]:
        """
        PDF yapısını analiz et
        
        Args:
            toc_start: Index başlangıç sayfası (opsiyonel, örn: 3)
            toc_end: Index bitiş sayfası (opsiyonel, örn: 8)
        """
        # İçindekiler sayfalarını bul veya kullan
        if toc_start is not None and toc_end is not None:
            toc_pages = list(range(toc_start, toc_end + 1))
        else:
            toc_pages = self._find_toc_pages()
        
        # Kategorileri çıkar
        categories = self._extract_categories_from_images(toc_pages) if toc_pages else []
        
        # Örnek bir sayfa analizi
        sample_page = self._analyze_sample_page(50) if self.total_pages > 50 else None
        
        return {
            "filename": Path(self.pdf_path).name,
            "total_pages": self.total_pages,
            "toc_pages": toc_pages,
            "categories": categories,
            "sample_page": sample_page
        }
    
    def _find_toc_pages(self) -> List[int]:
        """İçindekiler sayfalarını tespit et"""
        toc_pages = []
        
        # İlk 30 sayfayı tara
        for page_num in range(min(30, self.total_pages)):
            page = self.doc[page_num]
            text = page.get_text().lower()
            
            # İçindekiler veya sayfa numaraları içeren sayfalar
            # Bu PDF'de sayfa 3-7 arası index
            if any(word in text for word in ['contents', 'index', 'innehåll', 'inhalt']):
                toc_pages.append(page_num)
            # Sayfa numarası pattern'i fazla olan sayfalar (örn: "Belt guard module  103")
            elif text.count('\n') > 10 and len(re.findall(r'\s+\d{2,4}\s*$', text, re.MULTILINE)) > 5:
                toc_pages.append(page_num)
                
        return toc_pages
    
    def _extract_categories_from_images(self, toc_pages: List[int]) -> List[Dict[str, Any]]:
        """
        OCR kullanmadan, sadece layout analizi ile kategorileri çıkar
        Index sayfalarını render edip analiz eder
        """
        from PIL import Image
        import io
        
        categories = []
        current_main = None
        
        for page_num in toc_pages:
            page = self.doc[page_num]
            
            # Sayfayı image olarak render et
            pix = page.get_pixmap(dpi=150)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            
            # Text blokları al (pozisyon bilgisiyle)
            blocks = page.get_text("dict")["blocks"]
            
            for block in blocks:
                if block.get("type") != 0:
                    continue
                
                block_text = ""
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        block_text += span.get("text", "") + " "
                
                block_text = block_text.strip()
                
                if not block_text or len(block_text) < 5:
                    continue
                
                # Sayfa numarası var mı kontrol et (son 5 karakter)
                page_match = re.search(r'(\d{1,3})\s*$', block_text)
                
                if page_match:
                    page_ref = int(page_match.group(1))
                    # Sayfa numarasını çıkar
                    name = block_text[:page_match.start()].strip()
                    # Noktaları temizle
                    name = re.sub(r'[\.]{2,}', '', name).strip()
                    
                    if page_ref > 5 and page_ref < self.total_pages and len(name) > 5:
                        # Alt kategori mi ana kategori mi?
                        if current_main and block["bbox"][0] > 50:  # Girintili (x > 50)
                            current_main["subcategories"].append({
                                "name": name,
                                "page": page_ref - 1
                            })
                        else:
                            # Yeni kategori
                            new_cat = {
                                "name": name,
                                "page": page_ref - 1,
                                "subcategories": []
                            }
                            categories.append(new_cat)
                            current_main = new_cat
                else:
                    # Sayfa numarası yok, muhtemelen ana başlık
                    if len(block_text) > 5 and not block_text.isdigit():
                        current_main = {
                            "name": block_text,
                            "page": None,
                            "subcategories": []
                        }
                        categories.append(current_main)
        
        # Sadece geçerli olanları döndür
        result = []
        for cat in categories:
            if cat.get("subcategories") or cat.get("page") is not None:
                result.append(cat)
        
        return result[:50]
    
    def _extract_from_headers(self) -> List[Dict[str, Any]]:
        """Sayfa başlıklarından kategori çıkar"""
        categories = []
        seen = set()
        
        # Her 10 sayfada bir başlıkları kontrol et
        for page_num in range(10, min(self.total_pages, 200), 10):
            page = self.doc[page_num]
            blocks = page.get_text("dict")["blocks"]
            
            # En üstteki büyük yazıları bul
            for block in blocks[:3]:
                if block.get("type") == 0:  # Text block
                    for line in block.get("lines", []):
                        text = ""
                        for span in line.get("spans", []):
                            if span.get("size", 0) > 12:  # Büyük font
                                text += span.get("text", "")
                        
                        text = text.strip()
                        if text and len(text) > 5 and text not in seen:
                            seen.add(text)
                            categories.append({
                                "name": text,
                                "page": page_num,
                                "subcategories": []
                            })
        
        return categories[:15]
    
    def _analyze_sample_page(self, page_num: int) -> Dict[str, Any]:
        """Örnek sayfa analizi"""
        if page_num >= self.total_pages:
            page_num = self.total_pages // 2
            
        page = self.doc[page_num]
        
        # Görselleri say
        images = page.get_images()
        
        # Tabloları tespit et (basit)
        text = page.get_text()
        lines = text.split('\n')
        table_like_lines = sum(1 for line in lines if '\t' in line or '  ' in line)
        
        return {
            "page_number": page_num,
            "has_images": len(images) > 0,
            "image_count": len(images),
            "text_length": len(text),
            "potential_table_lines": table_like_lines
        }
    
    def extract_page_parts(self, page_num: int) -> Dict[str, Any]:
        """Belirli bir sayfadan parça listesini çıkar"""
        if page_num >= self.total_pages:
            return {"error": "Invalid page number"}
        
        page = self.doc[page_num]
        
        # Görsel çıkar
        images = []
        for img_index, img in enumerate(page.get_images()):
            xref = img[0]
            images.append({
                "index": img_index,
                "xref": xref
            })
        
        # Metin çıkar
        text = page.get_text()
        
        # Parça numaralarını bul (örnek: "123-456-789" veya "123456")
        part_pattern = r'\b\d{3,}[-\s]?\d{3,}[-\s]?\d{0,}\b'
        parts = []
        
        lines = text.split('\n')
        for line in lines:
            matches = re.findall(part_pattern, line)
            if matches:
                # Bu satırdaki tüm bilgiyi al
                parts.append({
                    "part_number": matches[0],
                    "description": line.replace(matches[0], '').strip(),
                    "raw_line": line
                })
        
        return {
            "page": page_num,
            "images": images,
            "parts": parts[:20],  # İlk 20 parça
            "total_parts_found": len(parts)
        }
    
    def get_page_image(self, page_num: int, zoom: float = 2.0) -> bytes:
        """Sayfayı görsel olarak al"""
        page = self.doc[page_num]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        return pix.tobytes("png")
    
    def close(self):
        """PDF'yi kapat"""
        self.doc.close()


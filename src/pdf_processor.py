import fitz  # PyMuPDF
import aiohttp
import aiofiles
import os
import logging
from typing import Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class PDFProcessor:
    """PDF işleme modülü: İndirme, Sayfa Sayısı, Önizleme Oluşturma"""
    
    def __init__(self, thumbnail_dir: str = "thumbnails"):
        self.thumbnail_dir = Path(thumbnail_dir)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)
    
    async def process_pdf(self, pdf_id: int, url: str) -> Optional[dict]:
        """PDF'i indirir ve meta verilerini (sayfa sayısı, önizleme) çıkarır"""
        temp_filename = f"temp_{pdf_id}.pdf"
        
        try:
            # 1. PDF'i indir (Kısmi indirme denenebilir ama sayfa sayısı ve kapak için genelde başı yeterli olmayabilir)
            # Şimdilik tamamını indiriyoruz, ileride stream edilebilir.
            success = await self._download_file(url, temp_filename)
            if not success:
                return None
            
            # 2. PDF'i analiz et
            page_count, thumbnail_path = self._analyze_pdf(temp_filename, pdf_id)
            file_size = os.path.getsize(temp_filename)
            
            # 3. Geçici dosyayı temizle
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
                
            return {
                "page_count": page_count,
                "thumbnail_path": thumbnail_path,
                "file_size": file_size
            }
            
        except Exception as e:
            logger.error(f"PDF işleme hatası (ID: {pdf_id}): {e}")
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
            return None

    async def _download_file(self, url: str, dest: str) -> bool:
        """Dosyayı asenkron olarak indirir"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        f = await aiofiles.open(dest, mode='wb')
                        await f.write(await response.read())
                        await f.close()
                        return True
                    else:
                        logger.warning(f"İndirme başarısız ({response.status}): {url}")
                        return False
        except Exception as e:
            logger.error(f"İndirme hatası: {e}")
            return False

    def _analyze_pdf(self, filepath: str, pdf_id: int) -> Tuple[int, str]:
        """PDF sayfa sayısını bulur ve ilk sayfadan resim oluşturur"""
        doc = fitz.open(filepath)
        page_count = doc.page_count
        
        # İlk sayfayı resim olarak kaydet
        page = doc.load_page(0)  # ilk sayfa
        pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5))  # 50% ölçekleme (hız ve boyut için)
        
        thumbnail_filename = f"pdf_{pdf_id}.png"
        thumbnail_path = self.thumbnail_dir / thumbnail_filename
        pix.save(str(thumbnail_path))
        
        doc.close()
        return page_count, str(thumbnail_path)


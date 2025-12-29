import asyncio
import logging
import json
from typing import List, Optional
from src.serper_client import SerperClient, SearchResult
from src.database import PEPCDatabase
from src.pdf_processor import PDFProcessor
from src.keywords import BRANDS, DOCUMENT_KEYWORDS, EQUIPMENT_KEYWORDS

logger = logging.getLogger(__name__)

class PEPCDiscovery:
    """Keşif ve Kuyruk Yönetimi"""
    
    def __init__(self, api_key: Optional[str] = None, db_path: Optional[str] = None):
        self.client = SerperClient(api_key)
        self.db = PEPCDatabase(db_path)
        self.processor = PDFProcessor()
        
    async def run_discovery(
        self,
        brands: List[str],
        doc_types: List[str] = None,
        equipment_types: List[str] = None,
        languages: List[str] = None
    ):
        """Toplu keşif başlatır ve sonuçları kuyruğa ekler"""
        if doc_types is None:
            doc_types = ["parts_catalog"]
        if languages is None:
            languages = ["en", "tr"]
            
        lang_to_country = {
            "en": "us", "de": "de", "fr": "fr", "es": "es",
            "it": "it", "pt": "br", "ru": "ru", "tr": "tr",
            "zh": "cn", "ja": "jp", "ko": "kr", "ar": "sa"
        }

        total_discovered = 0
        
        for brand in brands:
            brand_variants = BRANDS.get(brand.lower(), [brand])
            for doc_type in doc_types:
                for lang in languages:
                    doc_keywords = DOCUMENT_KEYWORDS.get(doc_type, {}).get(lang, [])
                    if not doc_keywords: continue
                    
                    # Basit bir sorgu kombinasyonu
                    for brand_name in brand_variants[:1]:
                        for doc_kw in doc_keywords[:1]:
                            query = f'"{doc_kw}" {brand_name}'
                            if equipment_types:
                                # Sadece ilk ekipman tipini ekle (sorgu sayısını azaltmak için)
                                query += f" {equipment_types[0]}"
                                
                            logger.info(f"Sorgulanıyor: {query} ({lang})")
                            try:
                                results = await self.client.search_pdfs(
                                    query=query,
                                    gl=lang_to_country.get(lang, "us"),
                                    hl=lang
                                )
                                
                                for r in results:
                                    # Veritabanına 'pending' olarak ekle
                                    pdf_id = self.db.add_pdf({
                                        "url": r.url,
                                        "title": r.title,
                                        "brand": brand,
                                        "doc_type": doc_type,
                                        "language": lang,
                                        "domain": r.domain,
                                        "status": "pending"
                                    })
                                    
                                    if pdf_id > 0:
                                        # İşleme görevini kuyruğa ekle
                                        self.db.add_task("processing", {"pdf_id": pdf_id, "url": r.url})
                                        total_discovered += 1
                                        
                            except Exception as e:
                                logger.error(f"Sorgu hatası '{query}': {e}")
                            
                            await asyncio.sleep(1) # Rate limiting
        
        # Session'ı kapat
        await self.client.close()
        return total_discovered

    async def process_queue(self):
        """Kuyruktaki görevleri işler"""
        while True:
            tasks = self.db.get_pending_tasks(limit=5)
            if not tasks:
                await asyncio.sleep(10)
                continue
                
            for task in tasks:
                task_id = task['id']
                payload = json.loads(task['payload'])
                
                self.db.update_task_status(task_id, "processing")
                
                try:
                    if task['task_type'] == "processing":
                        pdf_id = payload['pdf_id']
                        url = payload['url']
                        
                        logger.info(f"İşleniyor: {url}")
                        result = await self.processor.process_pdf(pdf_id, url)
                        
                        if result:
                            self.db.update_pdf_metadata(
                                pdf_id, 
                                result['page_count'], 
                                result['thumbnail_path'],
                                result['file_size']
                            )
                            # Durumu active yap
                            conn = self.db.get_connection()
                            conn.execute("UPDATE pdf_catalog SET status = 'active' WHERE id = ?", (pdf_id,))
                            conn.commit()
                            conn.close()
                            
                            self.db.update_task_status(task_id, "completed")
                        else:
                            self.db.update_task_status(task_id, "failed", "PDF işleme başarısız")
                            conn = self.db.get_connection()
                            conn.execute("UPDATE pdf_catalog SET status = 'broken' WHERE id = ?", (pdf_id,))
                            conn.commit()
                            conn.close()

                except Exception as e:
                    logger.error(f"Görev işleme hatası (ID: {task_id}): {e}")
                    self.db.update_task_status(task_id, "failed", str(e))
                
                await asyncio.sleep(1)


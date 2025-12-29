"""
Yandex Search API Client
IAM Token Authentication ile çalışır
https://yandex.cloud/en/docs/search-api/
"""
import jwt
import time
import requests
import json
import base64
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

from src.data.domains import is_excluded_domain

logger = logging.getLogger(__name__)


class YandexSearchClient:
    """Yandex Search API istemcisi - IAM Token Authentication"""
    
    def __init__(self):
        key_path = Path(__file__).parent.parent.parent / "authorized_key.json"
        with open(key_path, "r") as f:
            key_data = json.load(f)
        
        self.service_account_id = key_data["service_account_id"]
        self.key_id = key_data["id"]
        self.private_key = key_data["private_key"]
        self.folder_id = "b1gtkbakcmv86et9lq9r"
        self._token = None
        self._token_expires = 0
    
    def _get_iam_token(self) -> str:
        """IAM token al veya cache'den döndür"""
        now = int(time.time())
        if self._token and now < self._token_expires - 60:
            return self._token
        
        payload = {
            'aud': 'https://iam.api.cloud.yandex.net/iam/v1/tokens',
            'iss': self.service_account_id,
            'iat': now,
            'exp': now + 3600
        }
        
        encoded = jwt.encode(
            payload, 
            self.private_key, 
            algorithm='PS256', 
            headers={'kid': self.key_id}
        )
        
        response = requests.post(
            'https://iam.api.cloud.yandex.net/iam/v1/tokens',
            json={'jwt': encoded}
        )
        
        self._token = response.json()['iamToken']
        self._token_expires = now + 3600
        return self._token
    
    async def search(self, query: str, search_type: str = "SEARCH_TYPE_RU") -> List[Dict]:
        """
        Yandex Search API ile arama yap
        
        Args:
            query: Arama sorgusu
            search_type: Arama tipi (SEARCH_TYPE_RU, SEARCH_TYPE_TR)
        """
        try:
            token = self._get_iam_token()
            
            # Async arama başlat
            response = requests.post(
                "https://searchapi.api.cloud.yandex.net/v2/web/searchAsync",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={
                    "query": {
                        "searchType": search_type,
                        "queryText": query
                    },
                    "folderId": self.folder_id,
                    "responseFormat": "FORMAT_XML"
                },
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Yandex API error: {response.status_code} - {response.text}")
                return []
            
            operation = response.json()
            operation_id = operation.get('id')
            
            if not operation_id:
                logger.error(f"Yandex API: Operation ID alınamadı - {operation}")
                return []
            
            # Sonucu bekle (max 30 saniye)
            for _ in range(30):
                time.sleep(1)
                result = requests.get(
                    f"https://operation.api.cloud.yandex.net/operations/{operation_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30
                ).json()
                
                if result.get('done'):
                    raw_data = result.get('response', {}).get('rawData', '')
                    if raw_data:
                        xml_content = base64.b64decode(raw_data).decode('utf-8')
                        return self._parse_xml(xml_content)
                    return []
            
            return []
        except Exception as e:
            logger.error(f"Yandex search error: {e}")
            return []
    
    def _parse_xml(self, xml_content: str) -> List[Dict]:
        """XML'den sonuçları parse et"""
        results = []
        
        root = ET.fromstring(xml_content)
        for doc in root.findall('.//doc'):
            url = doc.find('url')
            title = doc.find('title')
            passage = doc.find('.//passage')
            mime = doc.find('mime-type')
            
            if url is not None:
                results.append({
                    'url': url.text,
                    'title': ''.join(title.itertext()) if title is not None else '',
                    'snippet': ''.join(passage.itertext()) if passage is not None else '',
                    'mime_type': mime.text if mime is not None else '',
                    'source': 'yandex'
                })
        
        return results
    
    async def search_pdfs(
        self,
        query: str,
        count: int = 50,
        language: str = "en"
    ) -> List[Dict]:
        """
        PDF dosyaları için arama yap
        
        Args:
            query: Arama sorgusu (mime:pdf eklenecek)
            count: İstenilen sonuç sayısı
            language: Dil kodu
        
        Note:
            Yandex filetype:pdf yerine mime:pdf kullanır
        """
        # Sorguya mime:pdf ekle (query_builder'dan gelen sorgu zaten içerebilir)
        if 'mime:pdf' not in query.lower() and 'filetype:pdf' in query.lower():
            query = query.replace('filetype:pdf', 'mime:pdf')
        elif 'mime:pdf' not in query.lower():
            query = f"{query} mime:pdf"
        
        # Dile göre search type belirle
        search_type_map = {
            "ru": "SEARCH_TYPE_RU",
            "tr": "SEARCH_TYPE_TR"
        }
        search_type = search_type_map.get(language, "SEARCH_TYPE_RU")
        
        results = await self.search(query, search_type=search_type)
        
        # PDF sonuçlarını filtrele ve formatla
        pdf_results = []
        for r in results:
            url = r.get('url', '')
            
            # PDF kontrolü
            if not (url.lower().endswith('.pdf') or 'pdf' in r.get('mime_type', '').lower()):
                continue
            
            # Hariç tutulan domain kontrolü
            if is_excluded_domain(url):
                continue
            
            pdf_results.append({
                'title': r.get('title', ''),
                'url': url,
                'description': r.get('snippet', ''),
                'source': 'yandex',
                'language': language
            })
        
        return pdf_results[:count]
    
    async def search_site(
        self,
        domain: str,
        query: str = "",
        count: int = 20
    ) -> List[Dict]:
        """
        Belirli bir sitede arama yap
        
        Args:
            domain: Site domain'i
            query: Ek arama sorgusu
            count: İstenilen sonuç sayısı
        """
        # Yandex mime:pdf kullanır
        site_query = f"site:{domain} mime:pdf"
        if query:
            site_query = f"{query} {site_query}"
        
        results = await self.search(site_query)
        
        formatted_results = []
        for r in results:
            if not is_excluded_domain(r.get('url', '')):
                formatted_results.append({
                    'title': r.get('title', ''),
                    'url': r.get('url', ''),
                    'description': r.get('snippet', ''),
                    'source': 'yandex'
                })
        
        return formatted_results[:count]
    
    async def close(self):
        """Session'ı kapat (uyumluluk için)"""
        pass


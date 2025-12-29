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


class YandexSearchClient:
    """Yandex Search API istemcisi - IAM Token Authentication"""
    
    def __init__(self):
        key_path = Path(__file__).parent.parent / "authorized_key.json"
        with open(key_path, "r") as f:
            key_data = json.load(f)
        
        self.service_account_id = key_data["service_account_id"]
        self.key_id = key_data["id"]
        self.private_key = key_data["private_key"]
        self.folder_id = "b1gtkbakcmv86et9lq9r"
        self._token = None
        self._token_expires = 0
    
    def _get_iam_token(self):
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
    
    async def search(self, query: str, search_type: str = "SEARCH_TYPE_RU", page: int = 0, per_page: int = 100) -> list:
        """
        Yandex Search API ile arama yap
        
        Args:
            query: Arama sorgusu
            search_type: Arama tipi (SEARCH_TYPE_RU, SEARCH_TYPE_TR, vb.)
            page: Sayfa numarası (0'dan başlar)
            per_page: Sayfa başına sonuç (max 100)
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
                    "responseFormat": "FORMAT_XML",
                    "groupings": {
                        "groupBy": "GROUPS_BY_DOC",
                        "docsInGroup": 1,
                        "groupsOnPage": min(per_page, 100),  # Max 100
                        "page": page
                    }
                },
                timeout=30
            )
            
            if response.status_code != 200:
                print(f"Yandex API error: {response.status_code} - {response.text}")
                return []
            
            operation = response.json()
            operation_id = operation.get('id')
            
            if not operation_id:
                print(f"Yandex API: Operation ID alınamadı - {operation}")
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
            print(f"Yandex search error: {e}")
            return []
    
    def _parse_xml(self, xml_content: str) -> list:
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
            query: Arama sorgusu
            count: İstenilen sonuç sayısı (max 100)
            language: Dil kodu
        """
        # Query zaten filetype:pdf içeriyorsa mime:pdf'e dönüştür (çift filtre engelle)
        if 'filetype:pdf' in query.lower():
            pdf_query = query.replace('filetype:pdf', 'mime:pdf').replace('filetype:PDF', 'mime:pdf')
        elif 'mime:pdf' not in query.lower():
            pdf_query = f"{query} mime:pdf"
        else:
            pdf_query = query
        
        # Dile göre search type belirle (Yandex sadece RU ve TR destekliyor)
        search_type_map = {
            "ru": "SEARCH_TYPE_RU",
            "tr": "SEARCH_TYPE_TR"
        }
        # Varsayılan olarak SEARCH_TYPE_RU kullan (en geniş sonuçlar)
        search_type = search_type_map.get(language, "SEARCH_TYPE_RU")
        
        # Pagination ile sonuçları topla
        all_results = []
        max_pages = min((count // 10) + 1, 5)  # Max 5 sayfa
        
        for page in range(max_pages):
            results = await self.search(pdf_query, search_type=search_type, page=page, per_page=50)
            if not results:
                break
            all_results.extend(results)
            if len(all_results) >= count:
                break
        
        # PDF sonuçlarını filtrele ve formatla
        pdf_results = []
        seen_urls = set()
        
        for r in all_results:
            url = r.get('url', '')
            
            # Duplicate kontrolü
            url_clean = url.lower().split('?')[0]
            if url_clean in seen_urls:
                continue
            seen_urls.add(url_clean)
            
            title = r.get('title', '').lower()
            snippet = r.get('snippet', '').lower()
            mime = r.get('mime_type', '').lower()
            
            # PDF kontrolü - URL, mime, title veya snippet'te pdf geçmeli
            is_pdf = (
                url.lower().endswith('.pdf') or
                '.pdf' in url.lower() or
                'pdf' in mime or
                'pdf' in title or
                'pdf' in snippet
            )
            
            if is_pdf:
                pdf_results.append({
                    'title': r.get('title', ''),
                    'url': url,
                    'description': r.get('snippet', ''),
                    'source': 'yandex',
                    'language': language
                })
                
                if len(pdf_results) >= count:
                    break
        
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

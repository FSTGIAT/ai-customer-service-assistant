"""
Keypoint Extractor for RAG Evaluation
Extracts and indexes individual keypoints with embeddings
"""

import os
import logging
import hashlib
from typing import List, Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class KeypointExtractor:
    """Extract and index keypoints from call summaries"""

    def __init__(self, opensearch_client):
        self.opensearch_client = opensearch_client
        self.embedding_service_url = os.getenv('EMBEDDING_SERVICE_URL', 'http://ml-service:5000')

    def extract_and_index(
        self,
        call_id: str,
        customer_id: str,
        key_points: List[str],
        context: str = '',
        call_date: Optional[str] = None
    ) -> int:
        """
        Extract keypoints and index them with embeddings

        Args:
            call_id: Parent call ID
            customer_id: Customer ID
            key_points: List of keypoint texts
            context: Summary context
            call_date: Date of the call
        """
        indexed_count = 0

        for i, keypoint_text in enumerate(key_points):
            if not keypoint_text or len(keypoint_text.strip()) < 5:
                continue

            try:
                # Generate keypoint ID
                keypoint_id = self._generate_keypoint_id(call_id, i, keypoint_text)

                # Classify keypoint type
                keypoint_type = self._classify_keypoint(keypoint_text)

                # Extract topics
                topics = self._extract_topics(keypoint_text)

                # Generate embedding (would call ML service in production)
                embedding = self._generate_embedding(keypoint_text)

                # Create document
                doc = {
                    'keypoint_id': keypoint_id,
                    'parent_call_id': call_id,
                    'customer_id': customer_id,
                    'keypoint_text': keypoint_text,
                    'keypoint_embedding': embedding,
                    'keypoint_type': keypoint_type,
                    'context': context[:500] if context else '',
                    'topics': topics,
                    'call_date': call_date,
                    'timestamp': datetime.now().isoformat()
                }

                # Index document
                if self.opensearch_client.index_document('call-keypoints', doc):
                    indexed_count += 1

            except Exception as e:
                logger.error(f"Failed to index keypoint {i} for call {call_id}: {e}")

        return indexed_count

    def _generate_keypoint_id(self, call_id: str, index: int, text: str) -> str:
        """Generate unique keypoint ID"""
        content = f"{call_id}_{index}_{text[:50]}"
        return f"kp_{hashlib.md5(content.encode()).hexdigest()[:16]}"

    def _classify_keypoint(self, text: str) -> str:
        """
        Classify keypoint type based on content

        Types: issue, resolution, request, complaint, question, info
        """
        text_lower = text.lower()

        # Hebrew keywords for classification
        issue_keywords = ['בעיה', 'תקלה', 'לא עובד', 'נפל', 'קרס']
        resolution_keywords = ['פתרון', 'תוקן', 'הסתדר', 'נפתר']
        request_keywords = ['מבקש', 'רוצה', 'צריך', 'אפשר']
        complaint_keywords = ['תלונה', 'לא מרוצה', 'גרוע', 'נורא']
        question_keywords = ['שאלה', 'למה', 'איך', 'מתי', 'האם']

        if any(kw in text_lower for kw in issue_keywords):
            return 'issue'
        elif any(kw in text_lower for kw in resolution_keywords):
            return 'resolution'
        elif any(kw in text_lower for kw in request_keywords):
            return 'request'
        elif any(kw in text_lower for kw in complaint_keywords):
            return 'complaint'
        elif any(kw in text_lower for kw in question_keywords):
            return 'question'
        else:
            return 'info'

    def _extract_topics(self, text: str) -> List[str]:
        """
        Extract topics from keypoint text

        Returns list of topic keywords
        """
        topics = []
        text_lower = text.lower()

        # Topic keywords (Hebrew)
        topic_map = {
            '5g': ['5g', '5G', 'דור 5', 'דור חמישי'],
            'internet': ['אינטרנט', 'חיבור', 'רשת', 'wifi', 'ווייפי'],
            'billing': ['חשבון', 'חיוב', 'תשלום', 'כסף'],
            'service': ['שירות', 'תמיכה', 'עזרה'],
            'device': ['מכשיר', 'טלפון', 'סמארטפון', 'ראוטר'],
            'speed': ['מהירות', 'איטי', 'מהיר'],
            'coverage': ['קליטה', 'כיסוי', 'אין רשת'],
            'plan': ['חבילה', 'תכנית', 'מסלול'],
            'international': ['חול', 'רומינג', 'בינלאומי']
        }

        for topic, keywords in topic_map.items():
            if any(kw in text_lower for kw in keywords):
                topics.append(topic)

        return topics

    def _generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for text

        In production, this would call the ML service.
        For now, returns a placeholder.
        """
        try:
            import requests

            response = requests.post(
                f"{self.embedding_service_url}/embeddings/generate",
                json={"text": text},
                timeout=30
            )

            if response.status_code == 200:
                return response.json().get('embedding', [])

        except Exception as e:
            logger.warning(f"Failed to generate embedding from ML service: {e}")

        # Return zero vector as placeholder (768 dimensions for AlephBERT)
        return [0.0] * 768

    def batch_extract_and_index(
        self,
        calls: List[Dict]
    ) -> Dict[str, int]:
        """
        Batch process multiple calls

        Args:
            calls: List of {call_id, customer_id, key_points, summary, call_date}
        """
        results = {
            'total_calls': len(calls),
            'total_keypoints': 0,
            'failed_calls': 0
        }

        for call in calls:
            try:
                count = self.extract_and_index(
                    call_id=call.get('call_id'),
                    customer_id=call.get('customer_id'),
                    key_points=call.get('key_points', []),
                    context=call.get('summary', ''),
                    call_date=call.get('call_date')
                )
                results['total_keypoints'] += count
            except Exception as e:
                logger.error(f"Failed to process call {call.get('call_id')}: {e}")
                results['failed_calls'] += 1

        return results

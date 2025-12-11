"""
OpenSearch Client for RAG Evaluation Service
Supports hybrid search (BM25 + kNN)
"""

import os
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from opensearchpy import OpenSearch, RequestsHttpConnection

logger = logging.getLogger(__name__)


class OpenSearchClient:
    """Client for OpenSearch operations including hybrid search"""

    def __init__(self):
        self.host = os.getenv('OPENSEARCH_URL', 'https://localhost:9200')
        self.username = os.getenv('OPENSEARCH_USERNAME', 'admin')
        self.password = os.getenv('OPENSEARCH_PASSWORD', 'admin')

        # Parse host
        if self.host.startswith('https://'):
            host = self.host.replace('https://', '')
            use_ssl = True
        else:
            host = self.host.replace('http://', '')
            use_ssl = False

        # Remove port if present
        if ':' in host:
            host, port = host.split(':')
            port = int(port)
        else:
            port = 443 if use_ssl else 9200

        self.client = OpenSearch(
            hosts=[{'host': host, 'port': port}],
            http_auth=(self.username, self.password),
            use_ssl=use_ssl,
            verify_certs=False,
            ssl_show_warn=False,
            connection_class=RequestsHttpConnection
        )

        logger.info(f"OpenSearch client initialized: {host}:{port}")

    def health_check(self) -> bool:
        """Check OpenSearch cluster health"""
        try:
            response = self.client.cluster.health()
            status = response.get('status', 'red')
            return status in ['green', 'yellow']
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def index_document(self, index: str, document: Dict) -> bool:
        """Index a document"""
        try:
            doc_id = document.get('evaluation_id') or document.get('keypoint_id')
            self.client.index(
                index=index,
                body=document,
                id=doc_id,
                refresh=True
            )
            return True
        except Exception as e:
            logger.error(f"Failed to index document: {e}")
            return False

    def bulk_index(self, index: str, documents: List[Dict]) -> Dict:
        """Bulk index documents"""
        try:
            actions = []
            for doc in documents:
                doc_id = doc.get('evaluation_id') or doc.get('keypoint_id')
                actions.append({'index': {'_index': index, '_id': doc_id}})
                actions.append(doc)

            response = self.client.bulk(body=actions, refresh=True)

            return {
                'success': not response.get('errors', False),
                'items': len(documents)
            }
        except Exception as e:
            logger.error(f"Bulk index failed: {e}")
            return {'success': False, 'error': str(e)}

    def hybrid_search(
        self,
        index: str,
        query_text: str,
        query_embedding: Optional[List[float]] = None,
        limit: int = 20,
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Perform hybrid search combining BM25 and kNN

        Args:
            index: Index name
            query_text: Text query for BM25
            query_embedding: Vector for kNN search (768-dim)
            limit: Maximum results
            bm25_weight: Weight for BM25 results (0-1)
            vector_weight: Weight for vector results (0-1)
            filters: Additional filters
        """
        try:
            # Build hybrid query
            queries = []

            # BM25 query
            bm25_query = {
                "match": {
                    "keypoint_text": {
                        "query": query_text,
                        "boost": bm25_weight
                    }
                }
            }
            queries.append(bm25_query)

            # kNN query (if embedding provided)
            if query_embedding:
                knn_query = {
                    "knn": {
                        "keypoint_embedding": {
                            "vector": query_embedding,
                            "k": limit * 2,
                            "boost": vector_weight
                        }
                    }
                }
                queries.append(knn_query)

            # Build search body
            search_body = {
                "size": limit,
                "query": {
                    "hybrid": {
                        "queries": queries
                    }
                },
                "search_pipeline": "hybrid-search-pipeline"
            }

            # Add filters if provided
            if filters:
                search_body["query"] = {
                    "bool": {
                        "must": [search_body["query"]],
                        "filter": [filters]
                    }
                }

            response = self.client.search(
                index=index,
                body=search_body
            )

            # Parse results
            results = []
            for hit in response.get('hits', {}).get('hits', []):
                result = hit.get('_source', {})
                result['_score'] = hit.get('_score', 0)
                result['_id'] = hit.get('_id')
                results.append(result)

            return results

        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            # Fallback to simple BM25 search
            return self._fallback_search(index, query_text, limit)

    def _fallback_search(self, index: str, query_text: str, limit: int) -> List[Dict]:
        """Fallback to simple BM25 search if hybrid fails"""
        try:
            response = self.client.search(
                index=index,
                body={
                    "size": limit,
                    "query": {
                        "match": {
                            "keypoint_text": query_text
                        }
                    }
                }
            )

            results = []
            for hit in response.get('hits', {}).get('hits', []):
                result = hit.get('_source', {})
                result['_score'] = hit.get('_score', 0)
                result['_id'] = hit.get('_id')
                results.append(result)

            return results

        except Exception as e:
            logger.error(f"Fallback search failed: {e}")
            return []

    def search_evaluations(
        self,
        hours: int = 24,
        strategy: Optional[str] = None
    ) -> List[Dict]:
        """Search evaluation records for metrics aggregation"""
        try:
            must_clauses = [
                {
                    "range": {
                        "timestamp": {
                            "gte": f"now-{hours}h"
                        }
                    }
                }
            ]

            if strategy:
                must_clauses.append({
                    "term": {"search_strategy": strategy}
                })

            response = self.client.search(
                index="rag-evaluations",
                body={
                    "size": 10000,
                    "query": {
                        "bool": {
                            "must": must_clauses
                        }
                    },
                    "sort": [{"timestamp": "desc"}]
                }
            )

            return [hit['_source'] for hit in response.get('hits', {}).get('hits', [])]

        except Exception as e:
            logger.error(f"Search evaluations failed: {e}")
            return []

    def update_document(self, index: str, doc_id: str, updates: Dict) -> bool:
        """Update a document"""
        try:
            self.client.update(
                index=index,
                id=doc_id,
                body={"doc": updates},
                refresh=True
            )
            return True
        except Exception as e:
            logger.error(f"Update document failed: {e}")
            return False

    def aggregate_metrics(self, index: str, hours: int = 24) -> Dict:
        """Aggregate metrics over time period"""
        try:
            response = self.client.search(
                index=index,
                body={
                    "size": 0,
                    "query": {
                        "range": {
                            "timestamp": {
                                "gte": f"now-{hours}h"
                            }
                        }
                    },
                    "aggs": {
                        "avg_precision_10": {"avg": {"field": "precision_at_10"}},
                        "avg_recall_10": {"avg": {"field": "recall_at_10"}},
                        "avg_recall_100": {"avg": {"field": "recall_at_100"}},
                        "avg_mrr": {"avg": {"field": "mrr"}},
                        "avg_latency": {"avg": {"field": "latency_ms"}},
                        "total_queries": {"value_count": {"field": "evaluation_id"}},
                        "by_strategy": {
                            "terms": {"field": "search_strategy"},
                            "aggs": {
                                "avg_accuracy": {"avg": {"field": "accuracy_score"}}
                            }
                        },
                        "feedback_breakdown": {
                            "terms": {"field": "user_feedback"}
                        }
                    }
                }
            )

            aggs = response.get('aggregations', {})

            return {
                'avg_precision_at_10': aggs.get('avg_precision_10', {}).get('value', 0),
                'avg_recall_at_10': aggs.get('avg_recall_10', {}).get('value', 0),
                'avg_recall_at_100': aggs.get('avg_recall_100', {}).get('value', 0),
                'avg_mrr': aggs.get('avg_mrr', {}).get('value', 0),
                'avg_latency_ms': aggs.get('avg_latency', {}).get('value', 0),
                'total_queries': aggs.get('total_queries', {}).get('value', 0),
                'by_strategy': {
                    bucket['key']: bucket['avg_accuracy']['value']
                    for bucket in aggs.get('by_strategy', {}).get('buckets', [])
                },
                'feedback': {
                    bucket['key']: bucket['doc_count']
                    for bucket in aggs.get('feedback_breakdown', {}).get('buckets', [])
                }
            }

        except Exception as e:
            logger.error(f"Aggregate metrics failed: {e}")
            return {}

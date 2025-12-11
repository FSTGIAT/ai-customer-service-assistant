"""
Accuracy Calculator for RAG Evaluation
Calculates Precision@K, Recall@K, MRR, NDCG
"""

import logging
import numpy as np
from typing import List, Dict, Optional, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class AccuracyCalculator:
    """Calculate retrieval accuracy metrics"""

    def __init__(self, opensearch_client):
        self.opensearch_client = opensearch_client

    def calculate_metrics(
        self,
        retrieved_ids: List[str],
        expected_ids: List[str],
        k_values: List[int] = [5, 10, 20, 100]
    ) -> Dict[str, float]:
        """
        Calculate all retrieval metrics

        Args:
            retrieved_ids: IDs of retrieved documents (in order)
            expected_ids: IDs of relevant documents (ground truth)
            k_values: K values for Precision@K and Recall@K
        """
        if not expected_ids:
            # No ground truth - return zeros
            return {
                'precision_at_5': 0.0,
                'precision_at_10': 0.0,
                'precision_at_20': 0.0,
                'recall_at_5': 0.0,
                'recall_at_10': 0.0,
                'recall_at_20': 0.0,
                'recall_at_100': 0.0,
                'mrr': 0.0,
                'ndcg': 0.0,
                'accuracy': 0.0
            }

        expected_set = set(expected_ids)

        # Calculate Precision@K and Recall@K for each K
        metrics = {}

        for k in k_values:
            retrieved_at_k = retrieved_ids[:k]
            relevant_at_k = len(set(retrieved_at_k) & expected_set)

            precision = relevant_at_k / k if k > 0 else 0.0
            recall = relevant_at_k / len(expected_set) if expected_set else 0.0

            metrics[f'precision_at_{k}'] = precision
            metrics[f'recall_at_{k}'] = recall

        # Calculate MRR (Mean Reciprocal Rank)
        metrics['mrr'] = self._calculate_mrr(retrieved_ids, expected_set)

        # Calculate NDCG
        metrics['ndcg'] = self._calculate_ndcg(retrieved_ids, expected_set)

        # Calculate overall accuracy (F1-like score)
        p10 = metrics.get('precision_at_10', 0)
        r10 = metrics.get('recall_at_10', 0)
        metrics['accuracy'] = 2 * (p10 * r10) / (p10 + r10) if (p10 + r10) > 0 else 0.0

        return metrics

    def _calculate_mrr(self, retrieved_ids: List[str], expected_set: set) -> float:
        """
        Calculate Mean Reciprocal Rank

        MRR = 1/rank of first relevant result
        """
        for i, doc_id in enumerate(retrieved_ids):
            if doc_id in expected_set:
                return 1.0 / (i + 1)
        return 0.0

    def _calculate_ndcg(
        self,
        retrieved_ids: List[str],
        expected_set: set,
        k: int = 10
    ) -> float:
        """
        Calculate Normalized Discounted Cumulative Gain

        NDCG = DCG / IDCG
        DCG = sum(rel_i / log2(i+1)) for i in 1..k
        """
        # Calculate DCG
        dcg = 0.0
        for i, doc_id in enumerate(retrieved_ids[:k]):
            rel = 1.0 if doc_id in expected_set else 0.0
            dcg += rel / np.log2(i + 2)  # +2 because log2(1) = 0

        # Calculate IDCG (ideal DCG - all relevant docs at top)
        ideal_rels = [1.0] * min(len(expected_set), k)
        ideal_rels.extend([0.0] * (k - len(ideal_rels)))

        idcg = 0.0
        for i, rel in enumerate(ideal_rels):
            idcg += rel / np.log2(i + 2)

        # NDCG
        return dcg / idcg if idcg > 0 else 0.0

    def batch_evaluate(
        self,
        queries: List[Dict],
        strategies: List[str] = ['hybrid']
    ) -> Dict[str, Any]:
        """
        Run batch evaluation against ground truth queries

        Args:
            queries: List of {query_text, expected_doc_ids}
            strategies: List of search strategies to test
        """
        results = defaultdict(lambda: {
            'precision_at_10': [],
            'recall_at_10': [],
            'recall_at_100': [],
            'mrr': [],
            'ndcg': []
        })

        for query in queries:
            query_text = query.get('query_text', '')
            expected_ids = query.get('expected_doc_ids', [])

            for strategy in strategies:
                # Execute search with this strategy
                bm25_weight = 0.3 if strategy == 'hybrid' else (1.0 if strategy == 'bm25' else 0.0)
                vector_weight = 0.7 if strategy == 'hybrid' else (0.0 if strategy == 'bm25' else 1.0)

                search_results = self.opensearch_client.hybrid_search(
                    index='call-keypoints',
                    query_text=query_text,
                    limit=100,
                    bm25_weight=bm25_weight,
                    vector_weight=vector_weight
                )

                retrieved_ids = [r.get('parent_call_id') or r.get('_id') for r in search_results]

                # Calculate metrics
                metrics = self.calculate_metrics(retrieved_ids, expected_ids)

                # Accumulate results
                results[strategy]['precision_at_10'].append(metrics['precision_at_10'])
                results[strategy]['recall_at_10'].append(metrics['recall_at_10'])
                results[strategy]['recall_at_100'].append(metrics['recall_at_100'])
                results[strategy]['mrr'].append(metrics['mrr'])
                results[strategy]['ndcg'].append(metrics['ndcg'])

        # Calculate averages
        summary = {}
        for strategy, metrics in results.items():
            summary[strategy] = {
                'avg_precision_at_10': np.mean(metrics['precision_at_10']),
                'avg_recall_at_10': np.mean(metrics['recall_at_10']),
                'avg_recall_at_100': np.mean(metrics['recall_at_100']),
                'avg_mrr': np.mean(metrics['mrr']),
                'avg_ndcg': np.mean(metrics['ndcg']),
                'queries_evaluated': len(metrics['precision_at_10'])
            }

        return summary

    def get_metrics_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get aggregated metrics summary from stored evaluations"""
        return self.opensearch_client.aggregate_metrics('rag-evaluations', hours)

#!/usr/bin/env python3
"""
RAG Evaluation Script - Standalone version
Run locally or on any machine with AWS credentials
No infrastructure deployment required - connects directly to OpenSearch and SQS

Usage:
    python run_evaluation.py --endpoint <opensearch-endpoint> --user admin --password <pass>

    Or set environment variables:
    export OPENSEARCH_ENDPOINT=<endpoint>
    export OPENSEARCH_USER=admin
    export OPENSEARCH_PASSWORD=<pass>
    python run_evaluation.py
"""
import os
import sys
import json
import time
import argparse
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from urllib.parse import urlparse
import urllib.request
import base64
import math

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    import boto3
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False
    logger.warning("boto3 not installed - CloudWatch metrics will be disabled")


@dataclass
class EvaluationResult:
    """Result of a RAG evaluation query"""
    query_id: str
    query_text: str
    expected_keypoints: List[str]
    retrieved_keypoints: List[str]
    precision_at_10: float
    recall_at_10: float
    recall_at_100: float
    mrr: float
    ndcg: float
    latency_ms: float
    search_strategy: str


class OpenSearchClient:
    """Simple OpenSearch client using urllib"""

    def __init__(self, endpoint: str, user: str, password: str):
        self.endpoint = endpoint.rstrip('/')
        self.auth = base64.b64encode(f"{user}:{password}".encode()).decode()

    def request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        url = f"https://{self.endpoint}{path}"
        headers = {
            'Authorization': f'Basic {self.auth}',
            'Content-Type': 'application/json'
        }
        data = json.dumps(body).encode() if body else None

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            logger.error(f"Request failed: {e.code} - {e.read().decode()}")
            raise

    def health(self) -> dict:
        return self.request('GET', '/_cluster/health')

    def search(self, index: str, query: dict) -> dict:
        return self.request('POST', f'/{index}/_search', query)


class RAGEvaluator:
    """RAG Evaluation metrics calculator"""

    def __init__(self, opensearch: OpenSearchClient, cloudwatch=None, environment: str = 'playground'):
        self.opensearch = opensearch
        self.cloudwatch = cloudwatch
        self.environment = environment

    @staticmethod
    def precision_at_k(retrieved: List[str], relevant: set, k: int) -> float:
        if k <= 0 or not retrieved:
            return 0.0
        top_k = retrieved[:k]
        relevant_in_top_k = sum(1 for item in top_k if item in relevant)
        return relevant_in_top_k / k

    @staticmethod
    def recall_at_k(retrieved: List[str], relevant: set, k: int) -> float:
        if not relevant:
            return 0.0
        top_k = retrieved[:k]
        relevant_in_top_k = sum(1 for item in top_k if item in relevant)
        return relevant_in_top_k / len(relevant)

    @staticmethod
    def mrr(retrieved: List[str], relevant: set) -> float:
        for i, item in enumerate(retrieved):
            if item in relevant:
                return 1.0 / (i + 1)
        return 0.0

    @staticmethod
    def ndcg(retrieved: List[str], relevant: set, k: int) -> float:
        def dcg(relevances: List[int]) -> float:
            return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))

        relevances = [1 if item in relevant else 0 for item in retrieved[:k]]
        ideal_relevances = sorted(relevances, reverse=True)

        actual_dcg = dcg(relevances)
        ideal_dcg = dcg(ideal_relevances)

        if ideal_dcg == 0:
            return 0.0
        return actual_dcg / ideal_dcg

    def search(self, query_text: str, index: str = "keypoints", k: int = 100) -> List[Dict]:
        """Perform BM25 search"""
        query = {
            "size": k,
            "query": {"match": {"text": query_text}},
            "_source": ["keypoint_id", "text", "call_id"]
        }

        try:
            response = self.opensearch.search(index, query)
            hits = response.get('hits', {}).get('hits', [])
            return [
                {
                    'keypoint_id': hit['_source'].get('keypoint_id'),
                    'text': hit['_source'].get('text'),
                    'score': hit['_score']
                }
                for hit in hits
            ]
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def evaluate(
        self,
        query_text: str,
        expected_keypoint_ids: List[str],
        index: str = "keypoints"
    ) -> EvaluationResult:
        """Evaluate a single query"""
        start_time = time.time()

        results = self.search(query_text, index, k=100)
        latency_ms = (time.time() - start_time) * 1000

        retrieved_ids = [r['keypoint_id'] for r in results if r.get('keypoint_id')]
        expected_set = set(expected_keypoint_ids)

        return EvaluationResult(
            query_id=f"eval_{int(time.time()*1000)}",
            query_text=query_text,
            expected_keypoints=expected_keypoint_ids,
            retrieved_keypoints=retrieved_ids[:10],
            precision_at_10=self.precision_at_k(retrieved_ids, expected_set, 10),
            recall_at_10=self.recall_at_k(retrieved_ids, expected_set, 10),
            recall_at_100=self.recall_at_k(retrieved_ids, expected_set, 100),
            mrr=self.mrr(retrieved_ids, expected_set),
            ndcg=self.ndcg(retrieved_ids, expected_set, 10),
            latency_ms=latency_ms,
            search_strategy='bm25'
        )

    def publish_metrics(self, result: EvaluationResult):
        """Publish metrics to CloudWatch"""
        if not self.cloudwatch:
            return

        try:
            self.cloudwatch.put_metric_data(
                Namespace='RAGEvaluation',
                MetricData=[
                    {
                        'MetricName': 'PrecisionAt10',
                        'Value': result.precision_at_10,
                        'Unit': 'None',
                        'Dimensions': [
                            {'Name': 'Environment', 'Value': self.environment},
                            {'Name': 'SearchStrategy', 'Value': result.search_strategy}
                        ]
                    },
                    {
                        'MetricName': 'RecallAt10',
                        'Value': result.recall_at_10,
                        'Unit': 'None',
                        'Dimensions': [
                            {'Name': 'Environment', 'Value': self.environment}
                        ]
                    },
                    {
                        'MetricName': 'MRR',
                        'Value': result.mrr,
                        'Unit': 'None',
                        'Dimensions': [
                            {'Name': 'Environment', 'Value': self.environment}
                        ]
                    },
                    {
                        'MetricName': 'QueryLatency',
                        'Value': result.latency_ms,
                        'Unit': 'Milliseconds',
                        'Dimensions': [
                            {'Name': 'Environment', 'Value': self.environment}
                        ]
                    }
                ]
            )
            logger.info(f"Metrics published for {result.query_id}")
        except Exception as e:
            logger.error(f"Failed to publish metrics: {e}")

    def run_batch(self, queries: List[Dict]) -> Dict:
        """Run batch evaluation"""
        results = []

        for query in queries:
            result = self.evaluate(
                query.get('query_text', ''),
                query.get('expected_keypoint_ids', [])
            )
            self.publish_metrics(result)
            results.append(asdict(result))

            logger.info(
                f"Query: '{query.get('query_text', '')[:50]}...' | "
                f"P@10: {result.precision_at_10:.3f} | "
                f"R@10: {result.recall_at_10:.3f} | "
                f"MRR: {result.mrr:.3f}"
            )

        # Calculate aggregates
        if results:
            avg_metrics = {
                'avg_precision_at_10': sum(r['precision_at_10'] for r in results) / len(results),
                'avg_recall_at_10': sum(r['recall_at_10'] for r in results) / len(results),
                'avg_mrr': sum(r['mrr'] for r in results) / len(results),
                'avg_latency_ms': sum(r['latency_ms'] for r in results) / len(results),
                'total_queries': len(results)
            }
        else:
            avg_metrics = {'total_queries': 0}

        return {
            'results': results,
            'aggregate': avg_metrics
        }


def main():
    parser = argparse.ArgumentParser(description='RAG Evaluation Script')
    parser.add_argument('--endpoint', default=os.environ.get('OPENSEARCH_ENDPOINT', ''),
                        help='OpenSearch endpoint')
    parser.add_argument('--user', default=os.environ.get('OPENSEARCH_USER', 'admin'),
                        help='OpenSearch username')
    parser.add_argument('--password', default=os.environ.get('OPENSEARCH_PASSWORD', ''),
                        help='OpenSearch password')
    parser.add_argument('--region', default=os.environ.get('AWS_REGION', 'eu-west-1'),
                        help='AWS region')
    parser.add_argument('--index', default='keypoints',
                        help='OpenSearch index to search')
    parser.add_argument('--queries-file', help='JSON file with evaluation queries')
    parser.add_argument('--query', help='Single query text to evaluate')
    parser.add_argument('--expected', nargs='+', help='Expected keypoint IDs for single query')
    parser.add_argument('--publish-metrics', action='store_true',
                        help='Publish metrics to CloudWatch')

    args = parser.parse_args()

    if not args.endpoint:
        logger.error("OpenSearch endpoint is required. Use --endpoint or set OPENSEARCH_ENDPOINT")
        sys.exit(1)

    if not args.password:
        logger.error("OpenSearch password is required. Use --password or set OPENSEARCH_PASSWORD")
        sys.exit(1)

    # Initialize clients
    opensearch = OpenSearchClient(args.endpoint, args.user, args.password)

    # Test connection
    try:
        health = opensearch.health()
        logger.info(f"Connected to OpenSearch cluster: {health.get('cluster_name')} (status: {health.get('status')})")
    except Exception as e:
        logger.error(f"Failed to connect to OpenSearch: {e}")
        sys.exit(1)

    # CloudWatch client (optional)
    cloudwatch = None
    if args.publish_metrics and HAS_BOTO3:
        cloudwatch = boto3.client('cloudwatch', region_name=args.region)
        logger.info("CloudWatch metrics publishing enabled")

    # Initialize evaluator
    evaluator = RAGEvaluator(opensearch, cloudwatch)

    # Run evaluation
    if args.queries_file:
        with open(args.queries_file, 'r') as f:
            queries = json.load(f)
        results = evaluator.run_batch(queries)

    elif args.query:
        expected = args.expected or []
        result = evaluator.evaluate(args.query, expected, args.index)
        evaluator.publish_metrics(result)
        results = asdict(result)

    else:
        # Demo mode with sample queries
        logger.info("No queries provided. Running in demo mode with sample queries.")
        sample_queries = [
            {"query_text": "תקלה בחשבונית", "expected_keypoint_ids": []},
            {"query_text": "שינוי חבילה", "expected_keypoint_ids": []},
            {"query_text": "ביטול שירות", "expected_keypoint_ids": []}
        ]
        results = evaluator.run_batch(sample_queries)

    # Print results
    print("\n" + "="*60)
    print("EVALUATION RESULTS")
    print("="*60)
    print(json.dumps(results, indent=2, ensure_ascii=False))

    return results


if __name__ == '__main__':
    main()

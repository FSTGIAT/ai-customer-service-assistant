"""
RAG Evaluation Lambda Function
Processes evaluation and feedback messages from SQS
Queries OpenSearch with hybrid search and publishes metrics to CloudWatch
"""
import os
import json
import time
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from urllib.parse import urlparse
import urllib.request
import base64

import boto3

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
OPENSEARCH_ENDPOINT = os.environ.get('OPENSEARCH_ENDPOINT', '')
OPENSEARCH_USER = os.environ.get('OPENSEARCH_USER', '')
OPENSEARCH_PASSWORD = os.environ.get('OPENSEARCH_PASSWORD', '')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'playground')
FEEDBACK_QUEUE_URL = os.environ.get('FEEDBACK_QUEUE_URL', '')

# AWS clients
cloudwatch = boto3.client('cloudwatch')
sqs = boto3.client('sqs')


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


def opensearch_request(method: str, path: str, body: Optional[dict] = None) -> dict:
    """Make authenticated request to OpenSearch"""
    url = f"https://{OPENSEARCH_ENDPOINT}{path}"

    # Basic auth header
    credentials = base64.b64encode(f"{OPENSEARCH_USER}:{OPENSEARCH_PASSWORD}".encode()).decode()
    headers = {
        'Authorization': f'Basic {credentials}',
        'Content-Type': 'application/json'
    }

    data = json.dumps(body).encode() if body else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        logger.error(f"OpenSearch request failed: {e.code} - {e.read().decode()}")
        raise
    except Exception as e:
        logger.error(f"OpenSearch request error: {str(e)}")
        raise


def calculate_precision_at_k(retrieved: List[str], relevant: set, k: int) -> float:
    """Calculate Precision@K"""
    if k <= 0 or not retrieved:
        return 0.0
    top_k = retrieved[:k]
    relevant_in_top_k = sum(1 for item in top_k if item in relevant)
    return relevant_in_top_k / k


def calculate_recall_at_k(retrieved: List[str], relevant: set, k: int) -> float:
    """Calculate Recall@K"""
    if not relevant:
        return 0.0
    top_k = retrieved[:k]
    relevant_in_top_k = sum(1 for item in top_k if item in relevant)
    return relevant_in_top_k / len(relevant)


def calculate_mrr(retrieved: List[str], relevant: set) -> float:
    """Calculate Mean Reciprocal Rank"""
    for i, item in enumerate(retrieved):
        if item in relevant:
            return 1.0 / (i + 1)
    return 0.0


def calculate_ndcg(retrieved: List[str], relevant: set, k: int) -> float:
    """Calculate Normalized Discounted Cumulative Gain"""
    import math

    def dcg(relevances: List[int]) -> float:
        return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))

    relevances = [1 if item in relevant else 0 for item in retrieved[:k]]
    ideal_relevances = sorted(relevances, reverse=True)

    actual_dcg = dcg(relevances)
    ideal_dcg = dcg(ideal_relevances)

    if ideal_dcg == 0:
        return 0.0
    return actual_dcg / ideal_dcg


def hybrid_search(query_text: str, query_vector: Optional[List[float]] = None, k: int = 100) -> List[Dict]:
    """Perform hybrid search combining BM25 and kNN"""

    # If no vector provided, use BM25 only
    if query_vector:
        query = {
            "size": k,
            "query": {
                "hybrid": {
                    "queries": [
                        {"match": {"text": {"query": query_text, "boost": 0.3}}},
                        {"knn": {"embedding": {"vector": query_vector, "k": k, "boost": 0.7}}}
                    ]
                }
            },
            "_source": ["keypoint_id", "text", "call_id"]
        }
    else:
        # BM25 only
        query = {
            "size": k,
            "query": {"match": {"text": query_text}},
            "_source": ["keypoint_id", "text", "call_id"]
        }

    try:
        response = opensearch_request('POST', '/keypoints/_search', query)
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
        logger.error(f"Search failed: {str(e)}")
        return []


def evaluate_query(
    query_text: str,
    expected_keypoint_ids: List[str],
    query_vector: Optional[List[float]] = None,
    search_strategy: str = 'hybrid'
) -> EvaluationResult:
    """Evaluate a single query against expected results"""
    start_time = time.time()

    results = hybrid_search(query_text, query_vector, k=100)
    latency_ms = (time.time() - start_time) * 1000

    retrieved_ids = [r['keypoint_id'] for r in results if r.get('keypoint_id')]
    expected_set = set(expected_keypoint_ids)

    return EvaluationResult(
        query_id=f"eval_{int(time.time()*1000)}",
        query_text=query_text,
        expected_keypoints=expected_keypoint_ids,
        retrieved_keypoints=retrieved_ids[:10],
        precision_at_10=calculate_precision_at_k(retrieved_ids, expected_set, 10),
        recall_at_10=calculate_recall_at_k(retrieved_ids, expected_set, 10),
        recall_at_100=calculate_recall_at_k(retrieved_ids, expected_set, 100),
        mrr=calculate_mrr(retrieved_ids, expected_set),
        ndcg=calculate_ndcg(retrieved_ids, expected_set, 10),
        latency_ms=latency_ms,
        search_strategy=search_strategy
    )


def publish_metrics(result: EvaluationResult):
    """Publish evaluation metrics to CloudWatch"""
    try:
        cloudwatch.put_metric_data(
            Namespace='RAGEvaluation',
            MetricData=[
                {
                    'MetricName': 'PrecisionAt10',
                    'Value': result.precision_at_10,
                    'Unit': 'None',
                    'Dimensions': [
                        {'Name': 'Environment', 'Value': ENVIRONMENT},
                        {'Name': 'SearchStrategy', 'Value': result.search_strategy}
                    ]
                },
                {
                    'MetricName': 'RecallAt10',
                    'Value': result.recall_at_10,
                    'Unit': 'None',
                    'Dimensions': [
                        {'Name': 'Environment', 'Value': ENVIRONMENT},
                        {'Name': 'SearchStrategy', 'Value': result.search_strategy}
                    ]
                },
                {
                    'MetricName': 'RecallAt100',
                    'Value': result.recall_at_100,
                    'Unit': 'None',
                    'Dimensions': [
                        {'Name': 'Environment', 'Value': ENVIRONMENT},
                        {'Name': 'SearchStrategy', 'Value': result.search_strategy}
                    ]
                },
                {
                    'MetricName': 'MRR',
                    'Value': result.mrr,
                    'Unit': 'None',
                    'Dimensions': [
                        {'Name': 'Environment', 'Value': ENVIRONMENT},
                        {'Name': 'SearchStrategy', 'Value': result.search_strategy}
                    ]
                },
                {
                    'MetricName': 'QueryLatency',
                    'Value': result.latency_ms,
                    'Unit': 'Milliseconds',
                    'Dimensions': [{'Name': 'Environment', 'Value': ENVIRONMENT}]
                }
            ]
        )
        logger.info(f"Metrics published for {result.query_id}")
    except Exception as e:
        logger.error(f"Failed to publish metrics: {str(e)}")


def process_evaluation(body: dict) -> dict:
    """Process an evaluation request"""
    query_text = body.get('query_text', '')
    expected_ids = body.get('expected_keypoint_ids', [])
    query_vector = body.get('query_vector')
    strategy = body.get('search_strategy', 'hybrid')

    if not query_text:
        return {'error': 'query_text is required'}

    result = evaluate_query(query_text, expected_ids, query_vector, strategy)
    publish_metrics(result)

    logger.info(f"Evaluation: P@10={result.precision_at_10:.3f}, R@10={result.recall_at_10:.3f}, MRR={result.mrr:.3f}")

    return asdict(result)


def process_feedback(body: dict) -> dict:
    """Process user feedback"""
    feedback_type = body.get('feedback_type', 'unknown')
    query_id = body.get('query_id', '')
    keypoint_id = body.get('keypoint_id', '')

    metric_name = 'FeedbackPositive' if feedback_type == 'positive' else 'FeedbackNegative'

    try:
        cloudwatch.put_metric_data(
            Namespace='RAGEvaluation',
            MetricData=[{
                'MetricName': metric_name,
                'Value': 1,
                'Unit': 'Count',
                'Dimensions': [{'Name': 'Environment', 'Value': ENVIRONMENT}]
            }]
        )
        logger.info(f"Feedback recorded: {feedback_type} for query {query_id}")
        return {'status': 'recorded', 'feedback_type': feedback_type}
    except Exception as e:
        logger.error(f"Failed to record feedback: {str(e)}")
        return {'error': str(e)}


def handler(event, context):
    """Lambda handler - processes SQS messages"""
    logger.info(f"Processing {len(event.get('Records', []))} records")

    results = []

    for record in event.get('Records', []):
        try:
            body = json.loads(record['body'])
            message_type = body.get('type', 'evaluation')

            # Determine message type from queue ARN or body
            event_source = record.get('eventSourceARN', '')

            if 'feedback' in event_source.lower() or message_type == 'feedback':
                result = process_feedback(body)
            else:
                result = process_evaluation(body)

            results.append({'messageId': record['messageId'], 'result': result})

        except Exception as e:
            logger.error(f"Error processing record: {str(e)}")
            results.append({'messageId': record.get('messageId'), 'error': str(e)})

    return {
        'statusCode': 200,
        'body': json.dumps({
            'processed': len(results),
            'results': results
        })
    }

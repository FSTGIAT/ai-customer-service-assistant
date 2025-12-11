"""
RAG Evaluation Service for Hebrew Call Analytics
Provides precision/recall testing and user feedback collection
"""
import os
import json
import time
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

import boto3
import structlog
from flask import Flask, jsonify, request
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
import numpy as np

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Flask app
app = Flask(__name__)

# Configuration
AWS_REGION = os.environ.get('AWS_REGION', 'eu-west-1')
OPENSEARCH_URL = os.environ.get('OPENSEARCH_URL', '')
EVALUATION_QUEUE_URL = os.environ.get('EVALUATION_QUEUE_URL', '')
KEYPOINT_QUEUE_URL = os.environ.get('KEYPOINT_QUEUE_URL', '')
FEEDBACK_QUEUE_URL = os.environ.get('FEEDBACK_QUEUE_URL', '')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'playground')

# AWS clients
sqs = boto3.client('sqs', region_name=AWS_REGION)
cloudwatch = boto3.client('cloudwatch', region_name=AWS_REGION)

# OpenSearch client
opensearch_client = None


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
    search_strategy: str  # 'hybrid', 'vector', 'bm25'


def init_opensearch():
    """Initialize OpenSearch client with AWS authentication"""
    global opensearch_client

    if not OPENSEARCH_URL:
        logger.warning("OpenSearch URL not configured")
        return None

    credentials = boto3.Session().get_credentials()
    auth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        AWS_REGION,
        'es',
        session_token=credentials.token
    )

    # Parse endpoint
    host = OPENSEARCH_URL.replace('https://', '').replace('http://', '')

    opensearch_client = OpenSearch(
        hosts=[{'host': host, 'port': 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection
    )

    logger.info("OpenSearch client initialized", host=host)
    return opensearch_client


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
    def dcg(relevances: List[int]) -> float:
        return sum(
            rel / np.log2(i + 2)
            for i, rel in enumerate(relevances)
        )

    # Relevance scores (1 for relevant, 0 for not)
    relevances = [1 if item in relevant else 0 for item in retrieved[:k]]

    # Ideal relevances (all relevant items at top)
    ideal_relevances = sorted(relevances, reverse=True)

    actual_dcg = dcg(relevances)
    ideal_dcg = dcg(ideal_relevances)

    if ideal_dcg == 0:
        return 0.0

    return actual_dcg / ideal_dcg


def hybrid_search(
    query_text: str,
    query_vector: List[float],
    index_name: str = "keypoints",
    k: int = 100,
    bm25_weight: float = 0.3,
    vector_weight: float = 0.7
) -> List[Dict[str, Any]]:
    """
    Perform hybrid search combining BM25 and kNN vector search
    """
    if not opensearch_client:
        logger.error("OpenSearch client not initialized")
        return []

    # Hybrid query combining BM25 and kNN
    query = {
        "size": k,
        "query": {
            "hybrid": {
                "queries": [
                    {
                        "match": {
                            "text": {
                                "query": query_text,
                                "boost": bm25_weight
                            }
                        }
                    },
                    {
                        "knn": {
                            "embedding": {
                                "vector": query_vector,
                                "k": k,
                                "boost": vector_weight
                            }
                        }
                    }
                ]
            }
        },
        "_source": ["keypoint_id", "text", "call_id", "timestamp"]
    }

    try:
        response = opensearch_client.search(index=index_name, body=query)
        hits = response.get('hits', {}).get('hits', [])
        return [
            {
                'keypoint_id': hit['_source'].get('keypoint_id'),
                'text': hit['_source'].get('text'),
                'score': hit['_score'],
                'call_id': hit['_source'].get('call_id')
            }
            for hit in hits
        ]
    except Exception as e:
        logger.error("Hybrid search failed", error=str(e))
        return []


def evaluate_query(
    query_text: str,
    expected_keypoint_ids: List[str],
    query_vector: Optional[List[float]] = None,
    search_strategy: str = 'hybrid'
) -> EvaluationResult:
    """
    Evaluate a single query against expected results
    """
    start_time = time.time()

    # Perform search based on strategy
    if search_strategy == 'hybrid' and query_vector:
        results = hybrid_search(query_text, query_vector, k=100)
    else:
        # Fallback to BM25 only
        results = bm25_search(query_text, k=100)

    latency_ms = (time.time() - start_time) * 1000

    # Extract retrieved keypoint IDs
    retrieved_ids = [r['keypoint_id'] for r in results if r.get('keypoint_id')]
    expected_set = set(expected_keypoint_ids)

    # Calculate metrics
    precision_at_10 = calculate_precision_at_k(retrieved_ids, expected_set, 10)
    recall_at_10 = calculate_recall_at_k(retrieved_ids, expected_set, 10)
    recall_at_100 = calculate_recall_at_k(retrieved_ids, expected_set, 100)
    mrr = calculate_mrr(retrieved_ids, expected_set)
    ndcg = calculate_ndcg(retrieved_ids, expected_set, 10)

    return EvaluationResult(
        query_id=f"eval_{int(time.time()*1000)}",
        query_text=query_text,
        expected_keypoints=expected_keypoint_ids,
        retrieved_keypoints=retrieved_ids[:10],
        precision_at_10=precision_at_10,
        recall_at_10=recall_at_10,
        recall_at_100=recall_at_100,
        mrr=mrr,
        ndcg=ndcg,
        latency_ms=latency_ms,
        search_strategy=search_strategy
    )


def bm25_search(query_text: str, k: int = 100) -> List[Dict[str, Any]]:
    """Perform BM25 text search only"""
    if not opensearch_client:
        return []

    query = {
        "size": k,
        "query": {
            "match": {
                "text": query_text
            }
        },
        "_source": ["keypoint_id", "text", "call_id"]
    }

    try:
        response = opensearch_client.search(index="keypoints", body=query)
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
        logger.error("BM25 search failed", error=str(e))
        return []


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
                    'Dimensions': [
                        {'Name': 'Environment', 'Value': ENVIRONMENT}
                    ]
                }
            ]
        )
        logger.info("Metrics published", query_id=result.query_id)
    except Exception as e:
        logger.error("Failed to publish metrics", error=str(e))


def process_evaluation_message(message: Dict):
    """Process an evaluation request from SQS"""
    body = json.loads(message['Body'])

    query_text = body.get('query_text', '')
    expected_ids = body.get('expected_keypoint_ids', [])
    query_vector = body.get('query_vector')
    strategy = body.get('search_strategy', 'hybrid')

    result = evaluate_query(query_text, expected_ids, query_vector, strategy)

    publish_metrics(result)

    logger.info(
        "Evaluation completed",
        query_id=result.query_id,
        precision=result.precision_at_10,
        recall=result.recall_at_10,
        mrr=result.mrr
    )

    return result


def process_feedback_message(message: Dict):
    """Process user feedback from SQS"""
    body = json.loads(message['Body'])

    feedback_type = body.get('feedback_type', 'unknown')  # 'positive' or 'negative'
    query_id = body.get('query_id', '')
    keypoint_id = body.get('keypoint_id', '')
    user_comment = body.get('comment', '')

    # Publish feedback metric
    metric_name = 'FeedbackPositive' if feedback_type == 'positive' else 'FeedbackNegative'

    try:
        cloudwatch.put_metric_data(
            Namespace='RAGEvaluation',
            MetricData=[
                {
                    'MetricName': metric_name,
                    'Value': 1,
                    'Unit': 'Count',
                    'Dimensions': [
                        {'Name': 'Environment', 'Value': ENVIRONMENT}
                    ]
                }
            ]
        )
        logger.info(
            "Feedback recorded",
            feedback_type=feedback_type,
            query_id=query_id,
            keypoint_id=keypoint_id
        )
    except Exception as e:
        logger.error("Failed to record feedback", error=str(e))


def sqs_worker():
    """Background worker to process SQS messages"""
    logger.info("SQS worker started")

    while True:
        try:
            # Process evaluation queue
            if EVALUATION_QUEUE_URL:
                response = sqs.receive_message(
                    QueueUrl=EVALUATION_QUEUE_URL,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=20
                )
                for message in response.get('Messages', []):
                    try:
                        process_evaluation_message(message)
                        sqs.delete_message(
                            QueueUrl=EVALUATION_QUEUE_URL,
                            ReceiptHandle=message['ReceiptHandle']
                        )
                    except Exception as e:
                        logger.error("Failed to process evaluation message", error=str(e))

            # Process feedback queue
            if FEEDBACK_QUEUE_URL:
                response = sqs.receive_message(
                    QueueUrl=FEEDBACK_QUEUE_URL,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=5
                )
                for message in response.get('Messages', []):
                    try:
                        process_feedback_message(message)
                        sqs.delete_message(
                            QueueUrl=FEEDBACK_QUEUE_URL,
                            ReceiptHandle=message['ReceiptHandle']
                        )
                    except Exception as e:
                        logger.error("Failed to process feedback message", error=str(e))

        except Exception as e:
            logger.error("SQS worker error", error=str(e))
            time.sleep(5)


# Flask routes
@app.route('/health')
def health():
    """Health check endpoint"""
    opensearch_healthy = False
    if opensearch_client:
        try:
            opensearch_client.cluster.health()
            opensearch_healthy = True
        except:
            pass

    return jsonify({
        'status': 'healthy',
        'opensearch': opensearch_healthy,
        'environment': ENVIRONMENT,
        'timestamp': time.time()
    })


@app.route('/evaluate', methods=['POST'])
def evaluate():
    """Synchronous evaluation endpoint for testing"""
    data = request.get_json()

    query_text = data.get('query_text', '')
    expected_ids = data.get('expected_keypoint_ids', [])
    query_vector = data.get('query_vector')
    strategy = data.get('search_strategy', 'hybrid')

    if not query_text:
        return jsonify({'error': 'query_text is required'}), 400

    result = evaluate_query(query_text, expected_ids, query_vector, strategy)
    publish_metrics(result)

    return jsonify(asdict(result))


@app.route('/batch_evaluate', methods=['POST'])
def batch_evaluate():
    """Batch evaluation endpoint"""
    data = request.get_json()
    queries = data.get('queries', [])

    results = []
    for query in queries:
        result = evaluate_query(
            query.get('query_text', ''),
            query.get('expected_keypoint_ids', []),
            query.get('query_vector'),
            query.get('search_strategy', 'hybrid')
        )
        publish_metrics(result)
        results.append(asdict(result))

    # Calculate aggregate metrics
    avg_precision = np.mean([r['precision_at_10'] for r in results]) if results else 0
    avg_recall = np.mean([r['recall_at_10'] for r in results]) if results else 0
    avg_mrr = np.mean([r['mrr'] for r in results]) if results else 0

    return jsonify({
        'results': results,
        'aggregate': {
            'avg_precision_at_10': avg_precision,
            'avg_recall_at_10': avg_recall,
            'avg_mrr': avg_mrr,
            'total_queries': len(results)
        }
    })


@app.route('/feedback', methods=['POST'])
def feedback():
    """Receive user feedback on search results"""
    data = request.get_json()

    feedback_type = data.get('feedback_type', '')
    query_id = data.get('query_id', '')
    keypoint_id = data.get('keypoint_id', '')

    if feedback_type not in ['positive', 'negative']:
        return jsonify({'error': 'feedback_type must be positive or negative'}), 400

    # Publish to SQS for async processing
    if FEEDBACK_QUEUE_URL:
        sqs.send_message(
            QueueUrl=FEEDBACK_QUEUE_URL,
            MessageBody=json.dumps(data)
        )

    return jsonify({'status': 'received', 'feedback_type': feedback_type})


@app.route('/metrics')
def metrics():
    """Get current evaluation metrics summary"""
    # This would typically query CloudWatch or a local cache
    return jsonify({
        'environment': ENVIRONMENT,
        'status': 'operational',
        'message': 'Query CloudWatch dashboard for detailed metrics'
    })


if __name__ == '__main__':
    # Initialize OpenSearch client
    init_opensearch()

    # Start SQS worker in background thread
    worker_thread = threading.Thread(target=sqs_worker, daemon=True)
    worker_thread.start()

    # Run Flask app
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)

#!/usr/bin/env python3
"""RAG Evaluation Service - ECS/Fargate Compatible"""
import os
import json
import time
import math
import threading
import boto3
import urllib.request
import base64
from flask import Flask, jsonify, request
from datetime import datetime

app = Flask(__name__)

# Configuration
OPENSEARCH_ENDPOINT = os.environ.get('OPENSEARCH_ENDPOINT')
OPENSEARCH_USER = os.environ.get('OPENSEARCH_USER', 'admin')
OPENSEARCH_PASSWORD = os.environ.get('OPENSEARCH_PASSWORD')
SQS_EVALUATION_QUEUE = os.environ.get('SQS_EVALUATION_QUEUE')
SQS_FEEDBACK_QUEUE = os.environ.get('SQS_FEEDBACK_QUEUE')
REGION = os.environ.get('AWS_REGION', 'eu-west-1')

sqs = boto3.client('sqs', region_name=REGION)
cloudwatch = boto3.client('cloudwatch', region_name=REGION)

class OpenSearchClient:
    def __init__(self, endpoint, user, password):
        self.endpoint = endpoint
        self.auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    
    def request(self, method, path, body=None):
        url = f"https://{self.endpoint}{path}"
        headers = {'Authorization': f'Basic {self.auth}', 'Content-Type': 'application/json'}
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    
    def search(self, index, query):
        return self.request('POST', f'/{index}/_search', query)
    
    def health(self):
        return self.request('GET', '/_cluster/health')

os_client = None

def get_opensearch():
    global os_client
    if os_client is None and OPENSEARCH_ENDPOINT and OPENSEARCH_PASSWORD:
        os_client = OpenSearchClient(OPENSEARCH_ENDPOINT, OPENSEARCH_USER, OPENSEARCH_PASSWORD)
    return os_client

class RAGEvaluator:
    @staticmethod
    def precision_at_k(retrieved, relevant, k):
        top_k = retrieved[:k]
        return sum(1 for x in top_k if x in relevant) / k if top_k else 0.0
    
    @staticmethod
    def recall_at_k(retrieved, relevant, k):
        if not relevant:
            return 0.0
        top_k = retrieved[:k]
        return sum(1 for x in top_k if x in relevant) / len(relevant)
    
    @staticmethod
    def mrr(retrieved, relevant):
        for i, item in enumerate(retrieved):
            if item in relevant:
                return 1.0 / (i + 1)
        return 0.0
    
    @staticmethod
    def ndcg(retrieved, relevant, k):
        def dcg(rels):
            return sum(rel / math.log2(i + 2) for i, rel in enumerate(rels))
        rels = [1 if x in relevant else 0 for x in retrieved[:k]]
        ideal = sorted(rels, reverse=True)
        return dcg(rels) / dcg(ideal) if dcg(ideal) > 0 else 0.0

def evaluate_query(query_text, expected_ids, index='keypoints'):
    client = get_opensearch()
    if not client:
        return None
    
    start = time.time()
    query = {"size": 100, "query": {"match": {"text": query_text}}, "_source": ["keypoint_id"]}
    
    try:
        result = client.search(index, query)
        latency = (time.time() - start) * 1000
        
        hits = result.get('hits', {}).get('hits', [])
        retrieved = [h['_source'].get('keypoint_id') for h in hits if h.get('_source')]
        expected = set(expected_ids)
        
        return {
            'query': query_text,
            'precision_at_10': RAGEvaluator.precision_at_k(retrieved, expected, 10),
            'recall_at_10': RAGEvaluator.recall_at_k(retrieved, expected, 10),
            'recall_at_100': RAGEvaluator.recall_at_k(retrieved, expected, 100),
            'mrr': RAGEvaluator.mrr(retrieved, expected),
            'ndcg_at_10': RAGEvaluator.ndcg(retrieved, expected, 10),
            'latency_ms': latency,
            'retrieved_count': len(retrieved)
        }
    except Exception as e:
        return {'error': str(e)}

def publish_metrics(metrics):
    try:
        data = [
            {'MetricName': 'PrecisionAt10', 'Value': metrics['precision_at_10'], 'Unit': 'None'},
            {'MetricName': 'RecallAt10', 'Value': metrics['recall_at_10'], 'Unit': 'None'},
            {'MetricName': 'RecallAt100', 'Value': metrics['recall_at_100'], 'Unit': 'None'},
            {'MetricName': 'MRR', 'Value': metrics['mrr'], 'Unit': 'None'},
            {'MetricName': 'NDCG', 'Value': metrics['ndcg_at_10'], 'Unit': 'None'},
            {'MetricName': 'QueryLatency', 'Value': metrics['latency_ms'], 'Unit': 'Milliseconds'}
        ]
        cloudwatch.put_metric_data(Namespace='RAGEvaluation', MetricData=data)
    except Exception as e:
        print(f"CloudWatch error: {e}")

def process_sqs_messages():
    """Background worker to process SQS messages"""
    while True:
        try:
            if SQS_EVALUATION_QUEUE:
                resp = sqs.receive_message(QueueUrl=SQS_EVALUATION_QUEUE, MaxNumberOfMessages=10, WaitTimeSeconds=20)
                for msg in resp.get('Messages', []):
                    body = json.loads(msg['Body'])
                    result = evaluate_query(body.get('query_text', ''), body.get('expected_ids', []))
                    if result and 'error' not in result:
                        publish_metrics(result)
                    sqs.delete_message(QueueUrl=SQS_EVALUATION_QUEUE, ReceiptHandle=msg['ReceiptHandle'])
        except Exception as e:
            print(f"SQS worker error: {e}")
            time.sleep(5)

# API Endpoints
@app.route('/health')
def health():
    client = get_opensearch()
    status = 'healthy' if client else 'degraded'
    try:
        if client:
            os_health = client.health()
            status = os_health.get('status', 'unknown')
    except:
        status = 'opensearch_error'
    return jsonify({'status': status, 'timestamp': datetime.now().isoformat()})

@app.route('/evaluate', methods=['POST'])
def evaluate():
    data = request.get_json()
    query_text = data.get('query_text', '')
    expected_ids = data.get('expected_ids', [])
    
    result = evaluate_query(query_text, expected_ids)
    if result and 'error' not in result:
        publish_metrics(result)
    
    return jsonify(result)

@app.route('/batch', methods=['POST'])
def batch_evaluate():
    data = request.get_json()
    queries = data.get('queries', [])
    results = []
    
    for q in queries:
        result = evaluate_query(q.get('query_text', ''), q.get('expected_ids', []))
        if result:
            results.append(result)
            if 'error' not in result:
                publish_metrics(result)
    
    # Aggregate
    if results:
        agg = {
            'total_queries': len(results),
            'avg_precision_at_10': sum(r.get('precision_at_10', 0) for r in results) / len(results),
            'avg_recall_at_100': sum(r.get('recall_at_100', 0) for r in results) / len(results),
            'avg_mrr': sum(r.get('mrr', 0) for r in results) / len(results),
            'avg_latency_ms': sum(r.get('latency_ms', 0) for r in results) / len(results)
        }
    else:
        agg = {'total_queries': 0}
    
    return jsonify({'results': results, 'aggregate': agg})

if __name__ == '__main__':
    print(f"Starting RAG Evaluation Service")
    print(f"OpenSearch: {OPENSEARCH_ENDPOINT}")
    print(f"SQS Queue: {SQS_EVALUATION_QUEUE}")
    
    # Start SQS worker thread
    if SQS_EVALUATION_QUEUE:
        worker = threading.Thread(target=process_sqs_messages, daemon=True)
        worker.start()
    
    # Run Flask
    app.run(host='0.0.0.0', port=8080)

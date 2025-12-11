"""
RAG Evaluation Service
Tracks accuracy, precision, recall, and user feedback for RAG queries
"""

import os
import logging
import asyncio
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Import services
from src.services.opensearch_client import OpenSearchClient
from src.services.accuracy_calculator import AccuracyCalculator
from src.services.feedback_processor import FeedbackProcessor
from src.services.sqs_consumer import SQSConsumer
from src.services.cloudwatch_metrics import CloudWatchMetrics
from src.services.keypoint_extractor import KeypointExtractor

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
CORS(app)

# Initialize services
opensearch_client = OpenSearchClient()
accuracy_calculator = AccuracyCalculator(opensearch_client)
feedback_processor = FeedbackProcessor(opensearch_client)
cloudwatch_metrics = CloudWatchMetrics()
keypoint_extractor = KeypointExtractor(opensearch_client)

# SQS consumers (started in background)
evaluation_consumer = None
feedback_consumer = None
keypoint_consumer = None


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Check OpenSearch connectivity
        os_healthy = opensearch_client.health_check()

        return jsonify({
            'status': 'healthy' if os_healthy else 'degraded',
            'service': 'evaluation-service',
            'timestamp': datetime.now().isoformat(),
            'components': {
                'opensearch': 'healthy' if os_healthy else 'unhealthy',
                'sqs_consumers': 'running'
            }
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500


@app.route('/evaluate', methods=['POST'])
def evaluate_query():
    """
    Evaluate a RAG query and calculate metrics

    Expected payload:
    {
        "query_text": "כמה לקוחות דיברו על 5G?",
        "query_embedding": [...],  # 768-dim vector
        "retrieved_doc_ids": ["call_123", "call_456", ...],
        "expected_doc_ids": ["call_123", "call_456", "call_789", ...],  # Ground truth
        "search_strategy": "hybrid",  # hybrid, vector, bm25
        "latency_ms": 150
    }
    """
    try:
        data = request.get_json()

        query_text = data.get('query_text', '')
        retrieved = data.get('retrieved_doc_ids', [])
        expected = data.get('expected_doc_ids', [])
        strategy = data.get('search_strategy', 'hybrid')
        latency_ms = data.get('latency_ms', 0)

        if not query_text:
            return jsonify({'error': 'query_text is required'}), 400

        # Calculate metrics
        metrics = accuracy_calculator.calculate_metrics(
            retrieved_ids=retrieved,
            expected_ids=expected
        )

        # Store evaluation in OpenSearch
        evaluation_doc = {
            'evaluation_id': f"eval_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            'query_text': query_text,
            'query_embedding': data.get('query_embedding'),
            'query_type': data.get('query_type', 'search'),
            'search_strategy': strategy,
            'retrieved_doc_ids': retrieved,
            'retrieved_count': len(retrieved),
            'expected_doc_ids': expected,
            'expected_count': len(expected),
            'precision_at_5': metrics['precision_at_5'],
            'precision_at_10': metrics['precision_at_10'],
            'precision_at_20': metrics['precision_at_20'],
            'recall_at_5': metrics['recall_at_5'],
            'recall_at_10': metrics['recall_at_10'],
            'recall_at_20': metrics['recall_at_20'],
            'recall_at_100': metrics['recall_at_100'],
            'mrr': metrics['mrr'],
            'ndcg': metrics['ndcg'],
            'accuracy_score': metrics['accuracy'],
            'latency_ms': latency_ms,
            'is_ground_truth': len(expected) > 0,
            'timestamp': datetime.now().isoformat()
        }

        opensearch_client.index_document('rag-evaluations', evaluation_doc)

        # Emit CloudWatch metrics
        cloudwatch_metrics.put_metric('PrecisionAt10', metrics['precision_at_10'])
        cloudwatch_metrics.put_metric('RecallAt10', metrics['recall_at_10'])
        cloudwatch_metrics.put_metric('RecallAt100', metrics['recall_at_100'])
        cloudwatch_metrics.put_metric('MRR', metrics['mrr'])
        cloudwatch_metrics.put_metric('QueryLatency', latency_ms, 'Milliseconds')
        cloudwatch_metrics.put_metric('QueryCount', 1)
        cloudwatch_metrics.put_metric(f'{strategy.title()}SearchAccuracy', metrics['accuracy'])

        if len(retrieved) == 0:
            cloudwatch_metrics.put_metric('ZeroResultQueries', 1)

        logger.info(f"Evaluation completed: P@10={metrics['precision_at_10']:.2f}, R@10={metrics['recall_at_10']:.2f}")

        return jsonify({
            'success': True,
            'evaluation_id': evaluation_doc['evaluation_id'],
            'metrics': metrics
        })

    except Exception as e:
        logger.error(f"Evaluation error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/feedback', methods=['POST'])
def submit_feedback():
    """
    Submit user feedback for a query result

    Expected payload:
    {
        "evaluation_id": "eval_...",
        "feedback": "positive" | "negative",
        "comment": "Missing some results"
    }
    """
    try:
        data = request.get_json()

        evaluation_id = data.get('evaluation_id')
        feedback = data.get('feedback')
        comment = data.get('comment', '')

        if not evaluation_id or not feedback:
            return jsonify({'error': 'evaluation_id and feedback are required'}), 400

        if feedback not in ['positive', 'negative']:
            return jsonify({'error': 'feedback must be "positive" or "negative"'}), 400

        # Process feedback
        result = feedback_processor.process_feedback(
            evaluation_id=evaluation_id,
            feedback=feedback,
            comment=comment
        )

        # Emit CloudWatch metrics
        if feedback == 'positive':
            cloudwatch_metrics.put_metric('FeedbackPositive', 1)
        else:
            cloudwatch_metrics.put_metric('FeedbackNegative', 1)

        logger.info(f"Feedback recorded: {evaluation_id} -> {feedback}")

        return jsonify({
            'success': True,
            'message': 'Feedback recorded'
        })

    except Exception as e:
        logger.error(f"Feedback error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/batch-evaluate', methods=['POST'])
def batch_evaluate():
    """
    Run batch evaluation against ground truth dataset

    Expected payload:
    {
        "ground_truth_queries": [
            {
                "query_text": "...",
                "expected_doc_ids": [...]
            },
            ...
        ],
        "search_strategies": ["hybrid", "vector", "bm25"]
    }
    """
    try:
        data = request.get_json()

        queries = data.get('ground_truth_queries', [])
        strategies = data.get('search_strategies', ['hybrid'])

        if not queries:
            return jsonify({'error': 'ground_truth_queries is required'}), 400

        results = accuracy_calculator.batch_evaluate(
            queries=queries,
            strategies=strategies
        )

        return jsonify({
            'success': True,
            'total_queries': len(queries),
            'strategies_tested': strategies,
            'results': results
        })

    except Exception as e:
        logger.error(f"Batch evaluation error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/metrics/summary', methods=['GET'])
def get_metrics_summary():
    """Get aggregated metrics summary"""
    try:
        # Get time range from query params
        hours = int(request.args.get('hours', 24))

        summary = accuracy_calculator.get_metrics_summary(hours=hours)

        return jsonify({
            'success': True,
            'time_range_hours': hours,
            'summary': summary
        })

    except Exception as e:
        logger.error(f"Metrics summary error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/keypoints/extract', methods=['POST'])
def extract_keypoints():
    """
    Extract keypoints from a call summary and index them

    Expected payload:
    {
        "call_id": "call_123",
        "customer_id": "cust_456",
        "summary": "...",
        "key_points": ["point1", "point2", ...],
        "call_date": "2024-01-15T10:00:00Z"
    }
    """
    try:
        data = request.get_json()

        call_id = data.get('call_id')
        customer_id = data.get('customer_id')
        key_points = data.get('key_points', [])

        if not call_id or not key_points:
            return jsonify({'error': 'call_id and key_points are required'}), 400

        # Extract and index keypoints
        indexed_count = keypoint_extractor.extract_and_index(
            call_id=call_id,
            customer_id=customer_id,
            key_points=key_points,
            context=data.get('summary', ''),
            call_date=data.get('call_date')
        )

        logger.info(f"Indexed {indexed_count} keypoints for call {call_id}")

        return jsonify({
            'success': True,
            'call_id': call_id,
            'keypoints_indexed': indexed_count
        })

    except Exception as e:
        logger.error(f"Keypoint extraction error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/search/hybrid', methods=['POST'])
def hybrid_search():
    """
    Perform hybrid search (BM25 + kNN) on keypoints

    Expected payload:
    {
        "query_text": "בעיות 5G",
        "query_embedding": [...],  # 768-dim vector (optional, will generate if not provided)
        "limit": 20,
        "bm25_weight": 0.3,
        "vector_weight": 0.7
    }
    """
    try:
        data = request.get_json()

        query_text = data.get('query_text', '')
        query_embedding = data.get('query_embedding')
        limit = data.get('limit', 20)
        bm25_weight = data.get('bm25_weight', 0.3)
        vector_weight = data.get('vector_weight', 0.7)

        if not query_text:
            return jsonify({'error': 'query_text is required'}), 400

        # Perform hybrid search
        results = opensearch_client.hybrid_search(
            index='call-keypoints',
            query_text=query_text,
            query_embedding=query_embedding,
            limit=limit,
            bm25_weight=bm25_weight,
            vector_weight=vector_weight
        )

        return jsonify({
            'success': True,
            'query': query_text,
            'total_results': len(results),
            'results': results
        })

    except Exception as e:
        logger.error(f"Hybrid search error: {e}")
        return jsonify({'error': str(e)}), 500


def start_sqs_consumers():
    """Start SQS consumer threads"""
    global evaluation_consumer, feedback_consumer, keypoint_consumer

    try:
        # Evaluation queue consumer
        evaluation_queue_url = os.getenv('EVALUATION_QUEUE_URL')
        if evaluation_queue_url:
            evaluation_consumer = SQSConsumer(
                queue_url=evaluation_queue_url,
                handler=handle_evaluation_message
            )
            evaluation_consumer.start()
            logger.info("Evaluation SQS consumer started")

        # Feedback queue consumer
        feedback_queue_url = os.getenv('FEEDBACK_QUEUE_URL')
        if feedback_queue_url:
            feedback_consumer = SQSConsumer(
                queue_url=feedback_queue_url,
                handler=handle_feedback_message
            )
            feedback_consumer.start()
            logger.info("Feedback SQS consumer started")

        # Keypoint queue consumer
        keypoint_queue_url = os.getenv('KEYPOINT_QUEUE_URL')
        if keypoint_queue_url:
            keypoint_consumer = SQSConsumer(
                queue_url=keypoint_queue_url,
                handler=handle_keypoint_message
            )
            keypoint_consumer.start()
            logger.info("Keypoint SQS consumer started")

    except Exception as e:
        logger.error(f"Failed to start SQS consumers: {e}")


def handle_evaluation_message(message):
    """Handle incoming evaluation message from SQS"""
    try:
        with app.app_context():
            # Process evaluation
            logger.info(f"Processing evaluation message: {message.get('query_text', '')[:50]}...")
            # Reuse the evaluate endpoint logic
            # ... implementation
            return True
    except Exception as e:
        logger.error(f"Error handling evaluation message: {e}")
        return False


def handle_feedback_message(message):
    """Handle incoming feedback message from SQS"""
    try:
        with app.app_context():
            feedback_processor.process_feedback(
                evaluation_id=message.get('evaluation_id'),
                feedback=message.get('feedback'),
                comment=message.get('comment', '')
            )
            return True
    except Exception as e:
        logger.error(f"Error handling feedback message: {e}")
        return False


def handle_keypoint_message(message):
    """Handle incoming keypoint extraction message from SQS"""
    try:
        with app.app_context():
            keypoint_extractor.extract_and_index(
                call_id=message.get('call_id'),
                customer_id=message.get('customer_id'),
                key_points=message.get('key_points', []),
                context=message.get('summary', ''),
                call_date=message.get('call_date')
            )
            return True
    except Exception as e:
        logger.error(f"Error handling keypoint message: {e}")
        return False


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))

    logger.info(f"Starting RAG Evaluation Service on port {port}")

    # Start SQS consumers
    start_sqs_consumers()

    # Run Flask app
    app.run(host='0.0.0.0', port=port, debug=False)

"""
Feedback Processor for RAG Evaluation
Handles user feedback on search results
"""

import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class FeedbackProcessor:
    """Process and store user feedback"""

    def __init__(self, opensearch_client):
        self.opensearch_client = opensearch_client

    def process_feedback(
        self,
        evaluation_id: str,
        feedback: str,
        comment: Optional[str] = None
    ) -> bool:
        """
        Process user feedback for an evaluation

        Args:
            evaluation_id: ID of the evaluation
            feedback: 'positive' or 'negative'
            comment: Optional feedback comment
        """
        try:
            # Update the evaluation document with feedback
            updates = {
                'user_feedback': feedback,
                'feedback_timestamp': datetime.now().isoformat()
            }

            if comment:
                updates['feedback_comment'] = comment

            success = self.opensearch_client.update_document(
                index='rag-evaluations',
                doc_id=evaluation_id,
                updates=updates
            )

            if success:
                logger.info(f"Feedback recorded for {evaluation_id}: {feedback}")

                # If negative feedback with expected results, update ground truth
                if feedback == 'negative' and comment:
                    self._process_negative_feedback(evaluation_id, comment)

            return success

        except Exception as e:
            logger.error(f"Failed to process feedback: {e}")
            return False

    def _process_negative_feedback(self, evaluation_id: str, comment: str):
        """
        Process negative feedback to potentially update ground truth

        This could trigger:
        - Manual review queue
        - Automatic ground truth updates
        - Retraining signals
        """
        try:
            # Log for manual review
            logger.warning(
                f"Negative feedback received for {evaluation_id}: {comment}"
            )

            # Could add to a review queue or trigger alerts
            # For now, just log

        except Exception as e:
            logger.error(f"Failed to process negative feedback: {e}")

    def get_feedback_stats(self, hours: int = 24) -> dict:
        """Get feedback statistics for time period"""
        try:
            evaluations = self.opensearch_client.search_evaluations(hours=hours)

            positive = sum(1 for e in evaluations if e.get('user_feedback') == 'positive')
            negative = sum(1 for e in evaluations if e.get('user_feedback') == 'negative')
            no_feedback = sum(1 for e in evaluations if not e.get('user_feedback'))

            total_with_feedback = positive + negative

            return {
                'total_evaluations': len(evaluations),
                'positive_feedback': positive,
                'negative_feedback': negative,
                'no_feedback': no_feedback,
                'positive_rate': positive / total_with_feedback if total_with_feedback > 0 else 0,
                'feedback_coverage': total_with_feedback / len(evaluations) if evaluations else 0
            }

        except Exception as e:
            logger.error(f"Failed to get feedback stats: {e}")
            return {}

"""
CloudWatch Metrics for RAG Evaluation Service
"""

import os
import logging
from typing import Optional, List, Dict
from datetime import datetime
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class CloudWatchMetrics:
    """Emit metrics to CloudWatch"""

    def __init__(self, namespace: str = 'RAGEvaluation'):
        self.namespace = namespace
        self.region = os.getenv('AWS_REGION', 'eu-west-1')

        self.cloudwatch = boto3.client(
            'cloudwatch',
            region_name=self.region
        )

        self._buffer: List[Dict] = []
        self._buffer_size = 20  # Flush after 20 metrics

    def put_metric(
        self,
        metric_name: str,
        value: float,
        unit: str = 'None',
        dimensions: Optional[Dict[str, str]] = None
    ):
        """
        Put a metric to CloudWatch

        Args:
            metric_name: Name of the metric
            value: Metric value
            unit: Unit (Count, Milliseconds, Percent, etc.)
            dimensions: Optional dimensions
        """
        try:
            metric_data = {
                'MetricName': metric_name,
                'Value': value,
                'Unit': unit,
                'Timestamp': datetime.utcnow()
            }

            if dimensions:
                metric_data['Dimensions'] = [
                    {'Name': k, 'Value': v}
                    for k, v in dimensions.items()
                ]

            self._buffer.append(metric_data)

            # Flush if buffer is full
            if len(self._buffer) >= self._buffer_size:
                self._flush()

        except Exception as e:
            logger.error(f"Failed to buffer metric {metric_name}: {e}")

    def _flush(self):
        """Flush buffered metrics to CloudWatch"""
        if not self._buffer:
            return

        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=self._buffer
            )
            logger.debug(f"Flushed {len(self._buffer)} metrics to CloudWatch")
            self._buffer = []

        except ClientError as e:
            logger.error(f"Failed to flush metrics: {e}")
            # Keep buffer for retry, but limit size
            if len(self._buffer) > 100:
                self._buffer = self._buffer[-50:]

    def put_metrics_batch(self, metrics: List[Dict]):
        """
        Put multiple metrics at once

        Args:
            metrics: List of {name, value, unit, dimensions}
        """
        for metric in metrics:
            self.put_metric(
                metric_name=metric.get('name'),
                value=metric.get('value'),
                unit=metric.get('unit', 'None'),
                dimensions=metric.get('dimensions')
            )

    def force_flush(self):
        """Force flush all buffered metrics"""
        self._flush()

    def get_metric_statistics(
        self,
        metric_name: str,
        start_time: datetime,
        end_time: datetime,
        period: int = 300,
        statistics: List[str] = ['Average', 'Sum', 'Maximum', 'Minimum']
    ) -> Dict:
        """
        Get metric statistics from CloudWatch

        Args:
            metric_name: Name of the metric
            start_time: Start of time range
            end_time: End of time range
            period: Period in seconds
            statistics: List of statistics to retrieve
        """
        try:
            response = self.cloudwatch.get_metric_statistics(
                Namespace=self.namespace,
                MetricName=metric_name,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=statistics
            )

            return {
                'metric_name': metric_name,
                'datapoints': response.get('Datapoints', [])
            }

        except ClientError as e:
            logger.error(f"Failed to get metric statistics: {e}")
            return {'metric_name': metric_name, 'datapoints': [], 'error': str(e)}

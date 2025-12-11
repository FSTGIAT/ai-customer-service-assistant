"""
SQS Consumer for RAG Evaluation Service
"""

import os
import json
import logging
import threading
import time
from typing import Callable, Optional
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class SQSConsumer:
    """Consume messages from SQS queue"""

    def __init__(
        self,
        queue_url: str,
        handler: Callable,
        max_messages: int = 10,
        wait_time_seconds: int = 20,
        visibility_timeout: int = 300
    ):
        self.queue_url = queue_url
        self.handler = handler
        self.max_messages = max_messages
        self.wait_time_seconds = wait_time_seconds
        self.visibility_timeout = visibility_timeout

        self.sqs = boto3.client(
            'sqs',
            region_name=os.getenv('AWS_REGION', 'eu-west-1')
        )

        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the consumer thread"""
        if self._running:
            logger.warning("Consumer already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info(f"SQS consumer started for {self.queue_url}")

    def stop(self):
        """Stop the consumer thread"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=30)
        logger.info("SQS consumer stopped")

    def _poll_loop(self):
        """Main polling loop"""
        while self._running:
            try:
                # Receive messages
                response = self.sqs.receive_message(
                    QueueUrl=self.queue_url,
                    MaxNumberOfMessages=self.max_messages,
                    WaitTimeSeconds=self.wait_time_seconds,
                    VisibilityTimeout=self.visibility_timeout,
                    MessageAttributeNames=['All']
                )

                messages = response.get('Messages', [])

                for message in messages:
                    self._process_message(message)

            except ClientError as e:
                logger.error(f"SQS error: {e}")
                time.sleep(5)

            except Exception as e:
                logger.error(f"Unexpected error in poll loop: {e}")
                time.sleep(5)

    def _process_message(self, message: dict):
        """Process a single message"""
        receipt_handle = message.get('ReceiptHandle')
        message_id = message.get('MessageId')

        try:
            # Parse message body
            body = json.loads(message.get('Body', '{}'))

            logger.info(f"Processing message {message_id}")

            # Call handler
            success = self.handler(body)

            if success:
                # Delete message on success
                self.sqs.delete_message(
                    QueueUrl=self.queue_url,
                    ReceiptHandle=receipt_handle
                )
                logger.info(f"Message {message_id} processed successfully")
            else:
                logger.warning(f"Handler returned False for message {message_id}")
                # Message will become visible again after visibility timeout

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in message {message_id}: {e}")
            # Delete invalid messages
            self.sqs.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle
            )

        except Exception as e:
            logger.error(f"Error processing message {message_id}: {e}")
            # Message will be retried or sent to DLQ

    def health_check(self) -> dict:
        """Check consumer health"""
        try:
            # Get queue attributes
            response = self.sqs.get_queue_attributes(
                QueueUrl=self.queue_url,
                AttributeNames=['ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible']
            )

            attrs = response.get('Attributes', {})

            return {
                'status': 'healthy' if self._running else 'stopped',
                'queue_url': self.queue_url,
                'messages_available': int(attrs.get('ApproximateNumberOfMessages', 0)),
                'messages_in_flight': int(attrs.get('ApproximateNumberOfMessagesNotVisible', 0))
            }

        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e)
            }

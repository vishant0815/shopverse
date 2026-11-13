import uuid

from django.db import models


class OutboxMessage(models.Model):
    """A message waiting to be published to Kafka, written in the same transaction as
    the change it describes (see docs/events.md)."""

    # Sending order. A timestamp isn't enough: every row written in one transaction gets
    # the same now(). Messages about one order are written one transaction at a time
    # (each locks the order), so for any one key this is also the order they happened in.
    seq = models.BigAutoField(primary_key=True)
    # The message id that consumers deduplicate on.
    message_id = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    topic = models.CharField(max_length=100)
    key = models.CharField(max_length=100)
    type = models.CharField(max_length=100)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "outbox"
        indexes = [
            # The relay asks "what hasn't been sent?" constantly; only unsent rows are
            # indexed, so the index stays tiny however big the table grows.
            models.Index(fields=["seq"], name="outbox_unsent", condition=models.Q(published_at__isnull=True)),
        ]


class ProcessedMessage(models.Model):
    """Every message id this service has handled, so a redelivered message is a no-op."""

    id = models.UUIDField(primary_key=True, editable=False)
    topic = models.CharField(max_length=100)
    type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "processed_messages"

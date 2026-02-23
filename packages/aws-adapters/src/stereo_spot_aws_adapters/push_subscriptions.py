"""DynamoDB store for Web Push subscriptions (job-events notifications)."""

import json
import os
from typing import Any

import boto3


class PushSubscriptionsStore:
    """Store push subscription payloads (endpoint = PK, subscription JSON)."""

    def __init__(
        self,
        table_name: str,
        *,
        region_name: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self._table_name = table_name
        self._resource = boto3.resource(
            "dynamodb",
            region_name=region_name,
            endpoint_url=endpoint_url,
        )
        self._table = self._resource.Table(table_name)

    def put(self, subscription: dict[str, Any]) -> None:
        """Store a push subscription. Uses subscription['endpoint'] as PK."""
        endpoint = subscription.get("endpoint") or ""
        self._table.put_item(
            Item={
                "endpoint": endpoint,
                "subscription": json.dumps(subscription),
            }
        )

    def delete(self, endpoint: str) -> None:
        """Remove a subscription by endpoint."""
        self._table.delete_item(Key={"endpoint": endpoint})

    def list_all(self) -> list[dict[str, Any]]:
        """Return all stored subscriptions (for sending Web Push)."""
        items = self._table.scan().get("Items", [])
        result = []
        for row in items:
            raw = row.get("subscription")
            if raw:
                try:
                    result.append(json.loads(raw))
                except (json.JSONDecodeError, TypeError):
                    pass
        return result


def push_subscriptions_store_from_env_or_none() -> PushSubscriptionsStore | None:
    """Build PushSubscriptionsStore when PUSH_SUBSCRIPTIONS_TABLE_NAME is set; else None."""
    table_name = os.environ.get("PUSH_SUBSCRIPTIONS_TABLE_NAME")
    if not table_name:
        return None
    region = os.environ.get("AWS_REGION")
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    return PushSubscriptionsStore(
        table_name,
        region_name=region,
        endpoint_url=endpoint,
    )

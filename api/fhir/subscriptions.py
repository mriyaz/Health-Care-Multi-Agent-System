"""
FHIR Subscriptions (rest-hook) — register with HAPI, receive notifications (Checklist #25, P1).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, status


def subscription_rest_hook_resource(
    *,
    criteria: str,
    callback_url: str,
    webhook_secret: str,
    reason: str = "HealthOS workflow trigger",
) -> dict[str, Any]:
    return {
        "resourceType": "Subscription",
        "status": "active",
        "reason": reason,
        "criteria": criteria,
        "channel": {
            "type": "rest-hook",
            "endpoint": callback_url,
            "payload": "application/fhir+json",
            "header": [f"X-FHIR-Webhook-Secret: {webhook_secret}"],
        },
    }


def verify_subscription_webhook(
    configured_secret: Optional[str],
    header_value: Optional[str],
) -> None:
    if not configured_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FHIR_WEBHOOK_SECRET is not configured",
        )
    if not header_value or header_value.strip() != configured_secret.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret"
        )

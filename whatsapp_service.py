"""
RH Business OS — WhatsApp AI Bot v0.1
WhatsApp Cloud API service layer
"""

import logging

import httpx

logger = logging.getLogger("rh-business-os.whatsapp")

GRAPH_API_VERSION = "v19.0"
GRAPH_API_BASE    = "https://graph.facebook.com"


class WhatsAppService:
    """
    Thin wrapper around the Meta WhatsApp Cloud API.
    Handles outbound message delivery.
    """

    def __init__(self, token: str, phone_number_id: str) -> None:
        self.token           = token
        self.phone_number_id = phone_number_id
        self.api_url         = (
            f"{GRAPH_API_BASE}/{GRAPH_API_VERSION}"
            f"/{phone_number_id}/messages"
        )

    async def send_text_message(self, to: str, body: str) -> bool:
        """
        Send a plain-text WhatsApp message.

        Args:
            to:   Recipient phone number in international format (e.g. 911234567890)
            body: Message text

        Returns:
            True on success, False on failure.
        """
        if not self.token or not self.phone_number_id:
            logger.error(
                "WHATSAPP_TOKEN or PHONE_NUMBER_ID is not set — cannot send message."
            )
            return False

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type":    "individual",
            "to":                to,
            "type":              "text",
            "text": {
                "preview_url": False,
                "body":        body,
            },
        }

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type":  "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                )

            if response.status_code == 200:
                logger.info(
                    "📤 Message sent | to=%s | response=%s",
                    to,
                    response.json(),
                )
                return True
            else:
                logger.error(
                    "❌ Failed to send message | to=%s | status=%s | body=%s",
                    to,
                    response.status_code,
                    response.text,
                )
                return False

        except httpx.RequestError as exc:
            logger.error("Network error sending message to %s: %s", to, exc)
            return False

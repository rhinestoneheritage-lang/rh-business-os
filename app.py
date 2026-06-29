"""
RH Business OS — WhatsApp AI Bot v0.1
FastAPI backend for Meta WhatsApp Cloud API webhook
"""

import json
import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from services.whatsapp_service import WhatsAppService

load_dotenv()

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("rh-business-os")

# ── Config ───────────────────────────────────────────────────────────────────
VERIFY_TOKEN      = os.getenv("VERIFY_TOKEN", "")
WHATSAPP_TOKEN    = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID   = os.getenv("PHONE_NUMBER_ID", "")
MESSAGES_FILE     = os.getenv("MESSAGES_FILE", "data/messages.json")
AUTO_REPLY_TEXT   = (
    "Welcome to Rhinestone Heritage. How can we help you?"
)

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="RH Business OS — WhatsApp AI Bot v0.1",
    description="Meta WhatsApp Cloud API webhook backend",
    version="0.1.0",
)

whatsapp = WhatsAppService(
    token=WHATSAPP_TOKEN,
    phone_number_id=PHONE_NUMBER_ID,
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _save_message(record: dict) -> None:
    """Append a message record to the JSON log file."""
    try:
        if os.path.exists(MESSAGES_FILE):
            with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
                messages = json.load(f)
        else:
            messages = []

        messages.append(record)

        with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)

    except Exception as exc:
        logger.error("Failed to save message to file: %s", exc)


# ── Webhook: GET — verification ───────────────────────────────────────────────
@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    Meta calls this endpoint to verify the webhook.
    Responds with hub.challenge if the token matches.
    """
    logger.info(
        "Webhook verification attempt | mode=%s token_match=%s",
        hub_mode,
        hub_verify_token == VERIFY_TOKEN,
    )

    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        logger.info("✅ Webhook verified successfully.")
        return PlainTextResponse(content=hub_challenge, status_code=200)

    logger.warning("❌ Webhook verification failed — token mismatch or bad mode.")
    raise HTTPException(status_code=403, detail="Forbidden: invalid verify token")


# ── Webhook: POST — incoming messages ─────────────────────────────────────────
@app.post("/webhook")
async def receive_webhook(request: Request):
    """
    Receives all events from Meta WhatsApp Cloud API.
    Handles incoming text messages, logs them, saves to JSON,
    and sends an auto-reply.
    """
    try:
        body = await request.json()
    except Exception:
        logger.error("Could not parse request body as JSON.")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    logger.info("📨 Webhook event received:\n%s", json.dumps(body, indent=2))

    # Validate it's a WhatsApp business account event
    if body.get("object") != "whatsapp_business_account":
        return JSONResponse(content={"status": "ignored"}, status_code=200)

    try:
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])

                for msg in messages:
                    msg_id      = msg.get("id")
                    from_number = msg.get("from")
                    timestamp   = msg.get("timestamp")
                    msg_type    = msg.get("type")

                    # Extract text body (ignore non-text for v0.1)
                    if msg_type == "text":
                        text_body = msg["text"]["body"]
                    else:
                        text_body = f"[{msg_type} message — not handled in v0.1]"

                    # ── Terminal log ──────────────────────────────────────
                    logger.info(
                        "💬 Message | from=%s | type=%s | body=%s",
                        from_number,
                        msg_type,
                        text_body,
                    )

                    # ── Build record ──────────────────────────────────────
                    record = {
                        "message_id":   msg_id,
                        "from":         from_number,
                        "timestamp":    timestamp,
                        "received_at":  datetime.utcnow().isoformat() + "Z",
                        "type":         msg_type,
                        "body":         text_body,
                        "raw":          msg,
                    }

                    # ── Save to JSON ──────────────────────────────────────
                    _save_message(record)
                    logger.info("💾 Message saved to %s", MESSAGES_FILE)

                    # ── Auto-reply ────────────────────────────────────────
                    if msg_type == "text":
                        reply_result = await whatsapp.send_text_message(
                            to=from_number,
                            body=AUTO_REPLY_TEXT,
                        )
                        if reply_result:
                            logger.info(
                                "✅ Auto-reply sent to %s", from_number
                            )
                        else:
                            logger.warning(
                                "⚠️  Auto-reply failed for %s", from_number
                            )

    except Exception as exc:
        logger.exception("Unexpected error processing webhook: %s", exc)
        # Always return 200 to Meta — otherwise it retries endlessly
        return JSONResponse(
            content={"status": "error", "detail": str(exc)},
            status_code=200,
        )

    return JSONResponse(content={"status": "ok"}, status_code=200)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/")
async def health():
    return {
        "service": "RH Business OS — WhatsApp AI Bot",
        "version": "0.1.0",
        "status":  "running",
    }

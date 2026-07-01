"""
RH Business OS — WhatsApp AI Bot v0.3
Conversation flow engine + Basic CRM for Rhinestone Heritage WhatsApp Bot.

State machine (per phone number):
  NEW
    └─► AWAITING_BUYER_TYPE      (sent welcome + menu)
          ├─► WHOLESALER_AWAITING_DESIGN   (reply "1")
          │     └─► WHOLESALER_AWAITING_MOQ  (any message / image received)
          │               └─► DONE
          └─► DONE                          (reply "2" or "3" → sent retail offer)

Sessions are persisted in data/sessions.json (keyed by phone number).
Messages are still appended to data/messages.json (immutable log).
whatsapp_service.py is UNCHANGED from v0.1.
"""

import json
import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from whatsapp_service import WhatsAppService

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("rh-business-os")

# ── Config ────────────────────────────────────────────────────────────────────
VERIFY_TOKEN    = os.getenv("VERIFY_TOKEN", "")
WHATSAPP_TOKEN  = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
MESSAGES_FILE   = os.getenv("MESSAGES_FILE", "data/messages.json")
SESSIONS_FILE   = os.getenv("SESSIONS_FILE", "data/sessions.json")
CUSTOMERS_FILE  = os.getenv("CUSTOMERS_FILE", "data/customers.json")

# ── States ────────────────────────────────────────────────────────────────────
STATE_NEW                    = "NEW"
STATE_AWAITING_BUYER_TYPE    = "AWAITING_BUYER_TYPE"
STATE_WHOLESALER_AWAITING_DESIGN = "WHOLESALER_AWAITING_DESIGN"
STATE_WHOLESALER_AWAITING_MOQ   = "WHOLESALER_AWAITING_MOQ"
STATE_DONE                   = "DONE"

# ── Reply templates ───────────────────────────────────────────────────────────
MSG_WELCOME = (
    "👋 Welcome to Rhinestone Heritage.\n\n"
    "Please select your buyer type:\n\n"
    "1️⃣ Wholesaler / Garment Manufacturer\n"
    "2️⃣ Retailer\n"
    "3️⃣ Personal Buyer\n\n"
    "Reply with 1, 2 or 3."
)

MSG_WHOLESALER_STEP1 = (
    "Thank you. 😊\n\n"
    "Kindly share a few reference images of the design you are looking for.\n\n"
    "Based on your requirements, we will suggest similar designs from our collection."
)

MSG_WHOLESALER_STEP2 = (
    "Thank you.\n\n"
    "Please share your approximate quantity (MOQ) for each design.\n\n"
    "Example:\n"
    "• 100 pcs\n"
    "• 500 pcs\n"
    "• 1000 pcs"
)

MSG_RETAIL_PERSONAL = (
    "Hello 👋\n\n"
    "Thank you for your interest in Rhinestone Heritage.\n\n"
    "✨ Premium Rhinestone Transfer Stickers available in hundreds of unique designs.\n\n"
    "🎉 LIMITED TIME OFFER\n"
    "✅ Flat 20% OFF on all Rhinestone Transfer Stickers\n\n"
    "💎 SPECIAL BONUS:\n"
    "Order above ₹5,000 and get an EXTRA 10% OFF on your purchase.\n\n"
    "🔥 Total Savings up to 30%\n\n"
    "Browse our collection:\n"
    "https://www.rhinestoneheritage.com/collections/rhinestone-transfer-stickers\n\n"
    "✔ Premium Quality\n"
    "✔ Easy Iron-On Application\n"
    "✔ Long Lasting Sparkle\n"
    "✔ Durable & Wash Safe\n\n"
    "Team Rhinestone Heritage"
)

MSG_INVALID_CHOICE = (
    "Please reply with 1, 2 or 3 to continue."
)

# Follow-up template (stored in session, NOT auto-sent)
MSG_FOLLOWUP_WHOLESALER = (
    "👋 Just following up.\n\n"
    "You can browse our latest Rhinestone Transfer Sticker Collection here:\n"
    "https://rhinestoneheritage.in/p/rhinestone-shirts-stickers\n\n"
    "Please send us the screenshot of your preferred design along with your "
    "required quantity (MOQ).\n\n"
    "We'll suggest the best options for your requirement. 😊"
)

# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(
    title="RH Business OS — WhatsApp AI Bot v0.3",
    description="Conversation flow engine + Basic CRM for Rhinestone Heritage",
    version="0.3.0",
)

whatsapp = WhatsAppService(
    token=WHATSAPP_TOKEN,
    phone_number_id=PHONE_NUMBER_ID,
)


# ── Session store (flat JSON, keyed by phone number) ──────────────────────────

def _load_sessions() -> dict:
    """Load all sessions from disk."""
    if not os.path.exists(SESSIONS_FILE):
        return {}
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Failed to load sessions: %s", exc)
        return {}


def _save_sessions(sessions: dict) -> None:
    """Persist all sessions to disk."""
    try:
        os.makedirs(os.path.dirname(SESSIONS_FILE), exist_ok=True)
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.error("Failed to save sessions: %s", exc)


def _get_session(phone: str) -> dict:
    """Return a session dict for this phone, creating one if absent."""
    sessions = _load_sessions()
    if phone not in sessions:
        sessions[phone] = {
            "phone":      phone,
            "state":      STATE_NEW,
            "buyer_type": None,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "followup_template": None,
        }
        _save_sessions(sessions)
    return sessions[phone]


def _update_session(phone: str, updates: dict) -> None:
    """Apply a dict of updates to a session and persist."""
    sessions = _load_sessions()
    if phone not in sessions:
        sessions[phone] = {}
    sessions[phone].update(updates)
    sessions[phone]["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _save_sessions(sessions)

# ── Customer CRM store (flat JSON, keyed by phone number) ─────────────────────

def _load_customers() -> dict:
    """Load all customer profiles from disk."""
    if not os.path.exists(CUSTOMERS_FILE):
        return {}
    try:
        with open(CUSTOMERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Failed to load customers: %s", exc)
        return {}


def _save_customers(customers: dict) -> None:
    """Persist all customer profiles to disk."""
    try:
        os.makedirs(os.path.dirname(CUSTOMERS_FILE), exist_ok=True)
        with open(CUSTOMERS_FILE, "w", encoding="utf-8") as f:
            json.dump(customers, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.error("Failed to save customers: %s", exc)


def _upsert_customer(
    phone: str,
    last_message: str,
    buyer_type: str | None = None,
    lead_status: str | None = None,
) -> None:
    """
    Create or update one customer profile.
    This is the first simple CRM layer for RH Business OS.
    """
    now = datetime.utcnow().isoformat() + "Z"
    customers = _load_customers()

    if phone not in customers:
        customers[phone] = {
            "phone_number": phone,
            "first_seen": now,
            "last_seen": now,
            "buyer_type": buyer_type,
            "lead_status": lead_status or "NEW_LEAD",
            "last_message": last_message,
            "message_count": 1,
        }
    else:
        customers[phone]["last_seen"] = now
        customers[phone]["last_message"] = last_message
        customers[phone]["message_count"] = customers[phone].get("message_count", 0) + 1

        if buyer_type is not None:
            customers[phone]["buyer_type"] = buyer_type
        if lead_status is not None:
            customers[phone]["lead_status"] = lead_status

    _save_customers(customers)



# ── Message log ───────────────────────────────────────────────────────────────

def _append_message(record: dict) -> None:
    """Append an incoming message record to the immutable log file."""
    try:
        os.makedirs(os.path.dirname(MESSAGES_FILE), exist_ok=True)
        if os.path.exists(MESSAGES_FILE):
            with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
                messages = json.load(f)
        else:
            messages = []

        messages.append(record)

        with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.error("Failed to save message: %s", exc)


# ── Conversation engine ───────────────────────────────────────────────────────

async def _handle_message(phone: str, msg_type: str, text_body: str) -> None:
    """
    Core state machine + Basic CRM.
    Important:
    - Update customer state BEFORE sending reply.
    - Prevent duplicate MOQ messages when customer sends multiple images.
    - Save/update customer profile in customers.json.
    """
    session = _get_session(phone)
    state = session.get("state", STATE_NEW)

    logger.info("📊 State | phone=%s state=%s", phone, state)

    # Save every inbound message to customer CRM first
    _upsert_customer(
        phone=phone,
        last_message=text_body,
        buyer_type=session.get("buyer_type"),
        lead_status="NEW_LEAD" if state == STATE_NEW else None,
    )

    # ── NEW: first contact ────────────────────────────────────────────────────
    if state == STATE_NEW:
        _update_session(phone, {"state": STATE_AWAITING_BUYER_TYPE})
        _upsert_customer(
            phone=phone,
            last_message=text_body,
            lead_status="WAITING_BUYER_TYPE",
        )
        await _reply(phone, MSG_WELCOME)
        return

    # ── AWAITING_BUYER_TYPE ───────────────────────────────────────────────────
    if state == STATE_AWAITING_BUYER_TYPE:
        choice = text_body.strip() if msg_type == "text" else ""

        if choice == "1":
            _update_session(phone, {
                "state": STATE_WHOLESALER_AWAITING_DESIGN,
                "buyer_type": "wholesaler",
                "followup_template": MSG_FOLLOWUP_WHOLESALER,
            })
            _upsert_customer(
                phone=phone,
                last_message=text_body,
                buyer_type="wholesaler",
                lead_status="WAITING_DESIGN",
            )
            await _reply(phone, MSG_WHOLESALER_STEP1)

        elif choice in ("2", "3"):
            buyer_type = "retailer" if choice == "2" else "personal"
            _update_session(phone, {
                "state": STATE_DONE,
                "buyer_type": buyer_type,
            })
            _upsert_customer(
                phone=phone,
                last_message=text_body,
                buyer_type=buyer_type,
                lead_status="WEBSITE_SENT",
            )
            await _reply(phone, MSG_RETAIL_PERSONAL)

        else:
            _upsert_customer(
                phone=phone,
                last_message=text_body,
                lead_status="WAITING_BUYER_TYPE",
            )
            await _reply(phone, MSG_INVALID_CHOICE)
        return

    # ── WHOLESALER_AWAITING_DESIGN ────────────────────────────────────────────
    if state == STATE_WHOLESALER_AWAITING_DESIGN:
        _update_session(phone, {"state": STATE_WHOLESALER_AWAITING_MOQ})
        _upsert_customer(
            phone=phone,
            last_message=text_body,
            buyer_type="wholesaler",
            lead_status="WAITING_MOQ",
        )
        await _reply(phone, MSG_WHOLESALER_STEP2)
        return

    # ── WHOLESALER_AWAITING_MOQ ───────────────────────────────────────────────
    if state == STATE_WHOLESALER_AWAITING_MOQ:
        # Extra images should only update customer last_message, not close the flow.
        if msg_type == "text":
            _update_session(phone, {"state": STATE_DONE})
            _upsert_customer(
                phone=phone,
                last_message=text_body,
                buyer_type="wholesaler",
                lead_status="QUALIFIED_LEAD",
            )
            await _reply(
                phone,
                "Thank you! 🙏 Our team will review your requirement and get back to you shortly."
            )
        else:
            _upsert_customer(
                phone=phone,
                last_message=text_body,
                buyer_type="wholesaler",
                lead_status="WAITING_MOQ",
            )
        return

    # ── DONE ──────────────────────────────────────────────────────────────────
    if state == STATE_DONE:
        _upsert_customer(
            phone=phone,
            last_message=text_body,
            buyer_type=session.get("buyer_type"),
        )
        await _reply(
            phone,
            "Thank you for reaching out to Rhinestone Heritage. "
            "Our team will be in touch with you. 🙏"
        )
        return

async def _reply(phone: str, text: str) -> None:
    """Send a text reply and log the outcome."""
    success = await whatsapp.send_text_message(to=phone, body=text)
    if success:
        logger.info("✅ Reply sent | to=%s", phone)
    else:
        logger.warning("⚠️  Reply failed | to=%s", phone)


# ── Webhook: GET — verification ───────────────────────────────────────────────
@app.get("/webhook")
async def verify_webhook(
    hub_mode: str         = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str    = Query(None, alias="hub.challenge"),
):
    logger.info(
        "Webhook verification | mode=%s token_match=%s",
        hub_mode,
        hub_verify_token == VERIFY_TOKEN,
    )
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        logger.info("✅ Webhook verified.")
        return PlainTextResponse(content=hub_challenge, status_code=200)

    logger.warning("❌ Webhook verification failed.")
    raise HTTPException(status_code=403, detail="Forbidden: invalid verify token")


# ── Webhook: POST — incoming messages ─────────────────────────────────────────
@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    logger.info("📨 Webhook received:\n%s", json.dumps(body, indent=2))

    if body.get("object") != "whatsapp_business_account":
        return JSONResponse(content={"status": "ignored"}, status_code=200)

    try:
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value    = change.get("value", {})
                messages = value.get("messages", [])

                for msg in messages:
                    msg_id      = msg.get("id")
                    from_number = msg.get("from")
                    timestamp   = msg.get("timestamp")
                    msg_type    = msg.get("type")

                    # Extract readable body for logging / state decisions
                    if msg_type == "text":
                        text_body = msg["text"]["body"]
                    elif msg_type == "image":
                        text_body = "[image]"
                    elif msg_type == "document":
                        text_body = "[document]"
                    elif msg_type == "audio":
                        text_body = "[audio]"
                    elif msg_type == "video":
                        text_body = "[video]"
                    else:
                        text_body = f"[{msg_type}]"

                    logger.info(
                        "💬 Message | from=%s type=%s body=%s",
                        from_number, msg_type, text_body,
                    )

                    # ── Log to messages.json ──────────────────────────────
                    _append_message({
                        "message_id":  msg_id,
                        "from":        from_number,
                        "timestamp":   timestamp,
                        "received_at": datetime.utcnow().isoformat() + "Z",
                        "type":        msg_type,
                        "body":        text_body,
                        "raw":         msg,
                    })

                    # ── Run conversation engine ───────────────────────────
                    await _handle_message(from_number, msg_type, text_body)

    except Exception as exc:
        logger.exception("Error processing webhook: %s", exc)
        # Always 200 to Meta — never let it retry on our errors
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
        "version": "0.3.0",
        "status":  "running",
    }

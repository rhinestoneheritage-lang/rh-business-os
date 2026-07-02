"""
RH Business OS — WhatsApp AI Bot v3.5
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
import csv
import io
import zipfile
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse

from whatsapp_service import WhatsAppService


# ── Premium Dark Theme Injector v10.2 ─────────────────────────────────────────
# This keeps every existing page/route working, but forces one consistent
# OREIUM black premium dashboard look across all HTML pages.
_BaseHTMLResponse = HTMLResponse

PREMIUM_DARK_THEME_CSS = """
<style id="oreium-global-dark-theme">
:root{--bg:#070A12;--panel:#0B1020;--panel2:#111827;--line:#243047;--text:#F8FAFC;--muted:#9CA3AF;--purple:#7C3AED;--blue:#1683FF;--green:#22C55E;--orange:#F97316;--pink:#EC4899;--danger:#EF4444;--shadow:0 20px 45px rgba(0,0,0,.28)}
*{box-sizing:border-box} html{background:#070A12!important} body{background:radial-gradient(circle at 20% 0%,rgba(124,58,237,.18),transparent 30%),linear-gradient(180deg,#070A12,#050712)!important;color:var(--text)!important;font-family:Inter,Arial,sans-serif!important;margin:0!important;min-height:100vh!important} 
a{color:#C084FC!important} h1,h2,h3,h4{color:#F8FAFC!important;letter-spacing:-.02em} p,div,span,td,th,label,small{border-color:rgba(255,255,255,.08)}
body>h1,body>h2,body>p,body>form,body>table,body>.card,body>.top,body>.grid,body>.panel,body>.quote{max-width:1280px;margin-left:auto!important;margin-right:auto!important}
.card,.panel,.quote,table,form:not(.search):not([style*="display:flex"]),.msg,.empty,.status-card,.kpi,.activity-item,.pro,div[style*="background:white"],div[style*="background: white"]{background:linear-gradient(180deg,rgba(17,24,39,.96),rgba(8,12,23,.96))!important;border:1px solid var(--line)!important;border-radius:18px!important;color:var(--text)!important;box-shadow:var(--shadow)!important}
table{background:linear-gradient(180deg,rgba(17,24,39,.96),rgba(8,12,23,.96))!important;border-collapse:separate!important;border-spacing:0!important;overflow:hidden!important;border:1px solid var(--line)!important;border-radius:18px!important;box-shadow:var(--shadow)!important} th{background:rgba(124,58,237,.18)!important;color:#D8B4FE!important;font-weight:800!important} td{color:#E5E7EB!important;border-bottom:1px solid rgba(255,255,255,.07)!important} tr:hover td{background:rgba(124,58,237,.06)!important}
input,select,textarea{background:#0A0F1D!important;color:#F8FAFC!important;border:1px solid var(--line)!important;border-radius:12px!important;outline:none!important} input::placeholder,textarea::placeholder{color:#6B7280!important} input:focus,select:focus,textarea:focus{border-color:#7C3AED!important;box-shadow:0 0 0 3px rgba(124,58,237,.18)!important}
button,a.btn,.btn,.refresh,.filter,.chip{background:linear-gradient(135deg,#7C3AED,#4F46E5)!important;color:white!important;border:0!important;border-radius:12px!important;text-decoration:none!important;font-weight:800!important;box-shadow:0 12px 28px rgba(124,58,237,.25)!important} button:hover,a.btn:hover,.btn:hover,.refresh:hover,.filter:hover,.chip:hover{filter:brightness(1.12)!important;transform:translateY(-1px)}
.filter:not(.active),.chip:not(.active),.refresh{background:#101827!important;border:1px solid var(--line)!important;color:#E5E7EB!important;box-shadow:none!important}.filter.active,.chip.active{background:linear-gradient(135deg,#7C3AED,#4F46E5)!important;color:white!important}
.label,.subtitle,.msg-time,.card-title,.empty,.empty-small,small{color:var(--muted)!important}.value,.phone,.phone-link,b,strong{color:#F8FAFC!important}.pill,.mini-pill{border-radius:999px!important;font-weight:800!important}.buyer{background:rgba(124,58,237,.18)!important;color:#C084FC!important}.qualified,.green{background:rgba(34,197,94,.15)!important;color:#4ADE80!important}.website,.orange{background:rgba(249,115,22,.15)!important;color:#FB923C!important}.waiting,.yellow{background:rgba(250,204,21,.15)!important;color:#FDE047!important}.new,.blue{background:rgba(22,131,255,.15)!important;color:#60A5FA!important}.purple{background:rgba(124,58,237,.18)!important;color:#C084FC!important}
.top,.header,.toolbar{background:transparent!important;color:var(--text)!important}.grid{gap:18px!important}.top a,.header a{margin:3px}.msg{margin-bottom:10px!important}.msg-body{color:#E5E7EB!important}.lastmsg{color:#D1D5DB!important}.card-value{color:#F8FAFC!important}
body:not(:has(.app))::before{content:'OREIUM Business OS';display:block;max-width:1280px;margin:0 auto 18px auto;padding:22px 24px;border-bottom:1px solid var(--line);font-weight:900;font-size:24px;color:#F8FAFC;background:linear-gradient(90deg,rgba(124,58,237,.16),transparent);border-radius:0 0 18px 18px} body:not(:has(.app)){padding:24px!important}
@media(max-width:800px){body:not(:has(.app)){padding:14px!important} table{display:block!important;overflow-x:auto!important}.grid{grid-template-columns:1fr!important}.top,.header,.toolbar{flex-direction:column!important;align-items:flex-start!important}}
</style>
"""


def _apply_premium_dark_theme(content: str) -> str:
    if not isinstance(content, str):
        return content
    low = content.lower()
    if "oreium-global-dark-theme" in low:
        return content
    # Wrap plain error pages so they also match the premium UI.
    if "<html" not in low:
        safe = str(content).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{PREMIUM_DARK_THEME_CSS}</head><body><div class='card' style='max-width:640px;margin:80px auto;padding:28px;'><h2>OREIUM Business OS</h2><p>{safe}</p><p><a class='btn' href='/dashboard?key={DASHBOARD_KEY}'>Back to Dashboard</a></p></div></body></html>"
    if "</head>" in low:
        idx = low.rfind("</head>")
        return content[:idx] + PREMIUM_DARK_THEME_CSS + content[idx:]
    return content.replace("<html", "<html", 1).replace(">", "><head>" + PREMIUM_DARK_THEME_CSS + "</head>", 1)


class HTMLResponse(_BaseHTMLResponse):
    def render(self, content) -> bytes:
        if isinstance(content, (str, bytes)):
            if isinstance(content, bytes):
                try:
                    content = content.decode(self.charset or "utf-8")
                except Exception:
                    return super().render(content)
            content = _apply_premium_dark_theme(content)
        return super().render(content)


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
DASHBOARD_KEY  = os.getenv("DASHBOARD_KEY", "RH2026")
ASSIGNEES = [name.strip() for name in os.getenv("CRM_ASSIGNEES", "Shifa,Hasan,Awais,Aquib").split(",") if name.strip()]
PIPELINE_STAGES = ["NEW", "CONTACTED", "QUALIFIED", "QUOTE_PENDING", "QUOTE_SENT", "SAMPLE", "ORDER_CONFIRMED", "DISPATCHED", "CLOSED", "LOST"]
TASK_STATUSES = ["OPEN", "IN_PROGRESS", "DONE"]

# v4.6-v6.5 module files
DOCUMENTS_FILE = os.getenv("DOCUMENTS_FILE", "data/documents.json")
DESIGN_REQUESTS_FILE = os.getenv("DESIGN_REQUESTS_FILE", "data/design_requests.json")
APPROVALS_FILE = os.getenv("APPROVALS_FILE", "data/approvals.json")
DISPATCH_FILE = os.getenv("DISPATCH_FILE", "data/dispatch.json")
PAYMENT_REMINDERS_FILE = os.getenv("PAYMENT_REMINDERS_FILE", "data/payment_reminders.json")
BROADCAST_QUEUE_FILE = os.getenv("BROADCAST_QUEUE_FILE", "data/broadcast_queue.json")
AUDIT_FILE = os.getenv("AUDIT_FILE", "data/audit.json")

QUICK_REPLY_TEMPLATES = {
    "catalogue": "Hello 👋\n\nThank you for contacting Rhinestone Heritage. You can browse our latest rhinestone transfer sticker collection here:\nhttps://www.rhinestoneheritage.com/collections/rhinestone-transfer-stickers\n\nPlease share the design screenshot and quantity you need.",
    "moq": "Thank you. Please share your approximate quantity (MOQ) for each design. Example: 100 pcs / 500 pcs / 1000 pcs.",
    "quote": "Thank you for sharing the details. Our team will check the design, size and quantity, then share the best quotation shortly.",
    "sample": "We can arrange a sample/design preview before bulk order confirmation. Please share size, colour and quantity details.",
    "payment": "Your order can be processed after payment confirmation. Please share the payment screenshot once done.",
}

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
    title="RH Business OS — WhatsApp AI Bot v6.5",
    description="Conversation flow engine + Basic CRM for Rhinestone Heritage",
    version="10.3.0",
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





def _append_outbound_message(phone: str, body: str, message_type: str = "text") -> None:
    """Append an outbound CRM/agent message to the immutable log file."""
    _append_message({
        "message_id": f"manual-{int(datetime.utcnow().timestamp())}",
        "from": "RH_BUSINESS_OS",
        "to": phone,
        "timestamp": str(int(datetime.utcnow().timestamp())),
        "received_at": datetime.utcnow().isoformat() + "Z",
        "direction": "outbound",
        "type": message_type,
        "body": body,
        "raw": {"source": "crm_manual_send"},
    })


def _customer_message_filter(message: dict, phone: str) -> bool:
    """Return messages belonging to one customer, inbound or outbound."""
    return str(message.get("from")) == str(phone) or str(message.get("to")) == str(phone)

def _load_messages() -> list:
    """Load message history."""
    if not os.path.exists(MESSAGES_FILE):
        return []
    try:
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Failed to load messages: %s", exc)
        return []


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




def _parse_followup_at(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None

def _followup_status(customer: dict) -> str:
    if customer.get("followup_done") is True:
        return "done"
    dt = _parse_followup_at(customer.get("followup_at"))
    if not dt:
        return "none"
    now = datetime.utcnow()
    if dt.date() == now.date():
        return "today"
    if dt < now:
        return "missed"
    return "upcoming"

def _format_followup(value: str | None) -> str:
    dt = _parse_followup_at(value)
    if not dt:
        return ""
    return dt.strftime("%d %b %Y, %I:%M %p")

# ── CRM Dashboard v1.5 ────────────────────────────────────────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(q: str = "", filter: str = "all", key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="""<!doctype html><html><body style='font-family:Arial;padding:40px;background:#070A12;color:white;'><div style='max-width:520px;margin:auto;background:#111827;padding:34px;border-radius:22px;text-align:center;border:1px solid #243047;'><h2>Access Denied</h2><p style='color:#9CA3AF;'>Please open dashboard with your secure key.</p><p style='color:#7C3AED;'>/dashboard?key=YOUR_KEY</p></div></body></html>""", status_code=401)

    customers = _load_customers()
    all_rows = list(customers.values())
    rows = list(all_rows)

    total = len(all_rows)
    wholesalers = sum(1 for c in all_rows if c.get("buyer_type") == "wholesaler")
    retailers = sum(1 for c in all_rows if c.get("buyer_type") == "retailer")
    personal = sum(1 for c in all_rows if c.get("buyer_type") == "personal")
    qualified = sum(1 for c in all_rows if c.get("lead_status") == "QUALIFIED_LEAD")
    website_sent = sum(1 for c in all_rows if c.get("lead_status") == "WEBSITE_SENT")
    hot_leads = sum(1 for c in all_rows if c.get("is_hot_lead") is True)
    today_followups = sum(1 for c in all_rows if _followup_status(c) == "today")
    missed_followups = sum(1 for c in all_rows if _followup_status(c) == "missed")
    upcoming_followups = sum(1 for c in all_rows if _followup_status(c) == "upcoming")
    assigned_leads = sum(1 for c in all_rows if c.get("assigned_to"))
    open_tasks = sum(1 for c in all_rows if c.get("task_text") and c.get("task_status") != "DONE")
    order_confirmed = sum(1 for c in all_rows if c.get("pipeline_stage") == "ORDER_CONFIRMED")

    query = (q or "").strip().lower()
    if filter == "wholesaler": rows = [c for c in rows if c.get("buyer_type") == "wholesaler"]
    elif filter == "retailer": rows = [c for c in rows if c.get("buyer_type") == "retailer"]
    elif filter == "personal": rows = [c for c in rows if c.get("buyer_type") == "personal"]
    elif filter == "qualified": rows = [c for c in rows if c.get("lead_status") == "QUALIFIED_LEAD"]
    elif filter == "website_sent": rows = [c for c in rows if c.get("lead_status") == "WEBSITE_SENT"]
    elif filter == "hot": rows = [c for c in rows if c.get("is_hot_lead") is True]
    elif filter == "followup_today": rows = [c for c in rows if _followup_status(c) == "today"]
    elif filter == "followup_missed": rows = [c for c in rows if _followup_status(c) == "missed"]
    elif filter == "followup_upcoming": rows = [c for c in rows if _followup_status(c) == "upcoming"]
    elif filter == "assigned": rows = [c for c in rows if c.get("assigned_to")]
    elif filter == "unassigned": rows = [c for c in rows if not c.get("assigned_to")]
    elif filter in ("Shifa", "Hasan", "Awais", "Aquib"): rows = [c for c in rows if c.get("assigned_to") == filter]
    elif filter == "tasks_open": rows = [c for c in rows if c.get("task_text") and c.get("task_status") != "DONE"]
    elif filter == "orders": rows = [c for c in rows if c.get("pipeline_stage") == "ORDER_CONFIRMED"]

    if query:
        rows = [c for c in rows if query in str(c.get("phone_number", "")).lower() or query in str(c.get("buyer_type", "")).lower() or query in str(c.get("lead_status", "")).lower() or query in str(c.get("last_message", "")).lower() or query in str(c.get("assigned_to", "")).lower()]

    def esc(value):
        if value is None: return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")
    def short_date(value):
        if not value: return ""
        return value.replace("T", " ").replace("Z", "")[:16]
    def pill_class(status):
        status = status or ""
        if status == "QUALIFIED_LEAD": return "green"
        if status == "WEBSITE_SENT": return "orange"
        if status in ("WAITING_DESIGN", "WAITING_MOQ", "WAITING_BUYER_TYPE", "FOLLOW_UP"): return "yellow"
        if status in ("CLOSED", "ORDER_CONFIRMED"): return "blue"
        return "purple"
    def filter_link(label, key_name):
        active = "active" if filter == key_name else ""
        return f'<a class="chip {active}" href="/dashboard?key={esc(DASHBOARD_KEY)}&filter={esc(key_name)}&q={esc(q)}">{label}</a>'
    def kpi(title, value, icon, color, sub=""):
        return f"""
        <div class='kpi {color}'>
            <div class='kpi-top'><div><div class='kpi-title'>{title}</div><div class='kpi-value'>{value}</div></div><div class='kpi-icon'>{icon}</div></div>
            <div class='kpi-sub'>{sub or 'Live business metric'}</div>
            <div class='spark'><i style='height:32%'></i><i style='height:46%'></i><i style='height:42%'></i><i style='height:60%'></i><i style='height:48%'></i><i style='height:72%'></i><i style='height:88%'></i></div>
        </div>"""

    rows_html = ""
    for c in sorted(rows, key=lambda x: x.get("last_seen", ""), reverse=True)[:80]:
        phone = esc(c.get("phone_number")); status = c.get("lead_status") or "NEW_LEAD"
        rows_html += f"""
        <tr><td><a class='phone-link' href='/customer/{phone}?key={esc(DASHBOARD_KEY)}'>{phone}</a></td><td><span class='mini-pill purple'>{esc(c.get('buyer_type') or 'unknown')}</span></td><td><span class='mini-pill {pill_class(status)}'>{esc(status)}</span></td><td>{esc(c.get('assigned_to') or 'Unassigned')}</td><td class='lastmsg'>{esc(c.get('last_message') or '')}</td><td>{esc(c.get('message_count') or 0)}</td><td>{esc(short_date(c.get('last_seen')))}</td></tr>"""
    if not rows_html: rows_html = "<tr><td colspan='7' class='empty-row'>No matching leads found.</td></tr>"

    recent_html = ""
    for c in sorted(all_rows, key=lambda x: x.get("last_seen", ""), reverse=True)[:5]:
        recent_html += f"""<div class='activity-item'><div class='dot'>✆</div><div class='activity-text'><b>{esc(c.get('phone_number'))}</b><span>{esc(c.get('last_message') or 'New activity')}</span></div><small>{esc(short_date(c.get('last_seen')))}</small></div>"""
    if not recent_html: recent_html = "<div class='empty-small'>No recent activity yet.</div>"

    html = f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><meta http-equiv='refresh' content='45'><title>OREIUM Business OS</title>
    <style>
    *{{box-sizing:border-box}}:root{{--bg:#070A12;--line:#243047;--text:#F8FAFC;--muted:#9CA3AF;--purple:#7C3AED;--blue:#1683FF;--green:#22C55E;--orange:#F97316;--pink:#EC4899}}
    body{{margin:0;background:radial-gradient(circle at 25% 0%,#1A1033 0,transparent 28%),var(--bg);color:var(--text);font-family:Inter,Arial,sans-serif}} .app{{display:grid;grid-template-columns:260px 1fr;min-height:100vh}}
    .sidebar{{border-right:1px solid var(--line);padding:22px 18px;background:linear-gradient(180deg,#0B1020,#070A12);position:sticky;top:0;height:100vh}} .brand{{display:flex;align-items:center;gap:12px;margin-bottom:26px}} .logo{{width:48px;height:48px;border-radius:16px;background:linear-gradient(135deg,#7C3AED,#3B0764);display:grid;place-items:center;font-weight:900;font-size:22px;box-shadow:0 12px 35px rgba(124,58,237,.38)}} .brand h2{{margin:0;font-size:24px}} .brand small{{color:var(--muted);font-weight:700;font-size:11px}}
    .nav{{display:flex;align-items:center;gap:12px;color:#D6D9E5;text-decoration:none;padding:13px 14px;border-radius:12px;margin:5px 0;font-size:15px}} .nav.active,.nav:hover{{background:linear-gradient(90deg,rgba(124,58,237,.95),rgba(124,58,237,.35));color:white}}
    .pro{{position:absolute;bottom:84px;left:18px;right:18px;padding:20px;border:1px solid var(--line);border-radius:16px;background:linear-gradient(135deg,rgba(124,58,237,.2),rgba(17,24,39,.8));text-align:center}} .version{{position:absolute;bottom:24px;color:var(--muted);font-size:12px}} .main{{padding:24px 24px 30px}}
    .topbar{{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:22px}} h1{{margin:0;font-size:24px}} .subtitle{{color:var(--muted);margin-top:6px}} .searchbar{{display:flex;gap:10px;align-items:center}} .search-input{{width:360px;background:#0A0F1D;border:1px solid var(--line);color:white;border-radius:14px;padding:13px 14px}} .btn{{background:#141B2B;color:white;border:1px solid var(--line);padding:12px 14px;border-radius:13px;text-decoration:none;cursor:pointer}} .btn.primary{{background:linear-gradient(135deg,#7C3AED,#4F46E5);border:0}}
    .kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:16px;margin-bottom:18px}} .kpi{{background:linear-gradient(180deg,rgba(17,24,39,.92),rgba(8,12,23,.92));border:1px solid var(--line);border-radius:16px;padding:18px;overflow:hidden;position:relative;min-height:160px}} .kpi:after{{content:'';position:absolute;inset:auto -30px -50px auto;width:170px;height:130px;filter:blur(35px);opacity:.3;background:var(--glow)}} .kpi.purple{{--glow:var(--purple)}}.kpi.blue{{--glow:var(--blue)}}.kpi.green{{--glow:var(--green)}}.kpi.orange{{--glow:var(--orange)}}.kpi.pink{{--glow:var(--pink)}} .kpi-top{{display:flex;justify-content:space-between;align-items:flex-start}} .kpi-title{{color:#D1D5DB;font-size:13px}} .kpi-value{{font-size:28px;font-weight:900;margin-top:8px}} .kpi-icon{{width:48px;height:48px;display:grid;place-items:center;border-radius:50%;background:var(--glow);font-size:22px}} .kpi-sub{{color:#22C55E;font-size:13px;margin-top:10px}} .spark{{display:flex;align-items:end;gap:6px;height:44px;margin-top:10px;opacity:.7}} .spark i{{flex:1;border-radius:8px 8px 0 0;background:linear-gradient(180deg,var(--glow),transparent)}}
    .grid{{display:grid;grid-template-columns:1.5fr 1fr 1.1fr;gap:16px;margin-bottom:16px}} .panel{{background:linear-gradient(180deg,rgba(17,24,39,.96),rgba(8,12,23,.96));border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 20px 45px rgba(0,0,0,.22)}} .panel-head{{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}} .panel h3{{margin:0;font-size:18px}} .view{{color:#A855F7;text-decoration:none;font-weight:700}}
    .chart{{height:260px;border-bottom:1px solid rgba(255,255,255,.08);border-left:1px solid rgba(255,255,255,.08);position:relative;overflow:hidden}} .chart:before{{content:'';position:absolute;inset:0;background:linear-gradient(to top,rgba(124,58,237,.28),transparent 60%),repeating-linear-gradient(to top,transparent 0 51px,rgba(255,255,255,.06) 52px);clip-path:polygon(0 78%,12% 58%,24% 38%,36% 50%,48% 30%,60% 48%,72% 28%,84% 34%,96% 12%,100% 20%,100% 100%,0 100%)}} .chart:after{{content:'';position:absolute;inset:0;background:linear-gradient(to top,rgba(22,131,255,.22),transparent 60%);clip-path:polygon(0 90%,14% 76%,25% 66%,37% 72%,50% 58%,63% 72%,75% 52%,86% 64%,96% 48%,100% 52%,100% 100%,0 100%)}}
    .activity-item{{display:grid;grid-template-columns:42px 1fr auto;gap:12px;align-items:center;padding:12px 0;border-bottom:1px solid rgba(255,255,255,.07)}} .dot{{width:38px;height:38px;border-radius:50%;display:grid;place-items:center;background:#22C55E;color:white;font-weight:800}} .activity-text b{{display:block;font-size:14px}} .activity-text span{{display:block;color:var(--muted);font-size:13px;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:260px}} .activity-item small{{color:var(--muted);font-size:12px}}
    .donut{{width:190px;height:190px;border-radius:50%;margin:18px auto;background:conic-gradient(var(--purple) 0 22%,var(--blue) 22% 44%,var(--orange) 44% 65%,var(--green) 65% 84%,var(--pink) 84% 100%);display:grid;place-items:center}} .donut-inner{{width:118px;height:118px;background:#0B1020;border-radius:50%;display:grid;place-items:center;text-align:center;font-size:13px;color:var(--muted)}} .donut-inner b{{display:block;color:white;font-size:30px}}
    .filters{{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 18px}} .chip{{color:#C9D2EA;background:#0B1020;border:1px solid var(--line);border-radius:999px;padding:9px 12px;text-decoration:none;font-size:13px}} .chip.active,.chip:hover{{background:linear-gradient(135deg,#7C3AED,#4F46E5);color:white;border-color:transparent}}
    table{{width:100%;border-collapse:collapse;overflow:hidden}} th,td{{padding:13px 12px;border-bottom:1px solid rgba(255,255,255,.07);text-align:left;font-size:13px;vertical-align:top}} th{{color:#9CA3AF;font-weight:800}} .phone-link{{color:white;text-decoration:none;font-weight:900}} .lastmsg{{max-width:360px;color:#D1D5DB}} .mini-pill{{padding:5px 9px;border-radius:999px;font-weight:800;font-size:11px;display:inline-block}} .mini-pill.green{{background:rgba(34,197,94,.15);color:#4ADE80}}.mini-pill.orange{{background:rgba(249,115,22,.15);color:#FB923C}}.mini-pill.yellow{{background:rgba(250,204,21,.16);color:#FDE047}}.mini-pill.blue{{background:rgba(22,131,255,.16);color:#60A5FA}}.mini-pill.purple{{background:rgba(124,58,237,.18);color:#C084FC}}
    .bottom-status{{display:grid;grid-template-columns:repeat(5,1fr);gap:14px}} .status-card{{background:#0D1220;border:1px solid var(--line);padding:14px;border-radius:15px;display:flex;gap:12px;align-items:center}} .status-icon{{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:rgba(124,58,237,.25)}} .status-card small{{color:var(--muted);display:block;margin-top:3px}} .empty-row,.empty-small{{color:var(--muted);text-align:center;padding:30px}}
    @media(max-width:1200px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.grid{{grid-template-columns:1fr}}.bottom-status{{grid-template-columns:repeat(2,1fr)}}}} @media(max-width:760px){{.app{{grid-template-columns:1fr}}.sidebar{{position:relative;height:auto}}.pro,.version{{display:none}}.topbar{{flex-direction:column;align-items:stretch}}.search-input{{width:100%}}.kpis{{grid-template-columns:1fr}}table{{display:block;overflow-x:auto}}}}
    </style></head><body><div class='app'><aside class='sidebar'><div class='brand'><div class='logo'>RH</div><div><h2>OREIUM</h2><small>BUSINESS OS</small></div></div>
    <a class='nav active' href='/dashboard?key={esc(DASHBOARD_KEY)}'><span>⌂</span>Dashboard</a><a class='nav' href='/dashboard?key={esc(DASHBOARD_KEY)}&filter=followup_today'><span>☘</span>WhatsApp <b style='margin-left:auto;background:#7C3AED;padding:2px 8px;border-radius:999px;'>{today_followups}</b></a><a class='nav' href='/dashboard?key={esc(DASHBOARD_KEY)}&filter=qualified'><span>♙</span>CRM</a><a class='nav' href='/quotes?key={esc(DASHBOARD_KEY)}'><span>▾</span>Sales</a><a class='nav' href='/production?key={esc(DASHBOARD_KEY)}'><span>⚙</span>Production</a><a class='nav' href='/inventory?key={esc(DASHBOARD_KEY)}'><span>□</span>Inventory</a><a class='nav' href='/staff?key={esc(DASHBOARD_KEY)}'><span>♧</span>HR</a><a class='nav' href='/reports?key={esc(DASHBOARD_KEY)}'><span>▥</span>Reports</a><a class='nav' href='/settings?key={esc(DASHBOARD_KEY)}'><span>⚙</span>Settings</a>
    <div class='pro'><div style='font-size:28px;'>♛</div><b>OREIUM PRO</b><p style='color:#9CA3AF;font-size:13px;'>Premium business dashboard</p><a class='btn primary' href='/system?key={esc(DASHBOARD_KEY)}'>System Center</a></div><div class='version'>v10.2.0 | Unified Premium UI</div></aside>
    <main class='main'><div class='topbar'><div><h1>Welcome back, Admin 👋</h1><div class='subtitle'>Here is what is happening in your business today.</div></div><div class='searchbar'><form method='get' action='/dashboard' style='display:flex;gap:10px;'><input type='hidden' name='key' value='{esc(DASHBOARD_KEY)}'><input type='hidden' name='filter' value='{esc(filter)}'><input class='search-input' name='q' value='{esc(q)}' placeholder='Search phone, status, message...'><button class='btn primary' type='submit'>Search</button></form><a class='btn' href='/dashboard/export?key={esc(DASHBOARD_KEY)}'>CSV</a></div></div>
    <section class='kpis'>{kpi('Total Leads', total, '₹', 'purple', '+18.6% vs last 7 days')}{kpi('New Leads', total, '👥', 'blue', str(wholesalers)+' wholesalers')}{kpi('Orders', order_confirmed, '🛍', 'green', 'Confirmed pipeline')}{kpi('Follow-ups', today_followups + missed_followups, '⏱', 'orange', str(missed_followups)+' missed')}{kpi('Pending Tasks', open_tasks, '☑', 'pink', 'Team work queue')}</section>
    <section class='grid'><div class='panel'><div class='panel-head'><h3>Business Overview</h3><a class='view' href='/reports?key={esc(DASHBOARD_KEY)}'>View Reports</a></div><div class='chart'></div></div><div class='panel'><div class='panel-head'><h3>Recent Activities</h3><a class='view' href='/dashboard?key={esc(DASHBOARD_KEY)}'>View All</a></div>{recent_html}</div><div class='panel'><div class='panel-head'><h3>Pipeline Overview</h3></div><div class='donut'><div class='donut-inner'><span>Total Deals</span><b>{total}</b></div></div><a class='view' href='/dashboard?key={esc(DASHBOARD_KEY)}&filter=qualified' style='display:block;text-align:center;'>View Full Pipeline →</a></div></section>
    <section class='grid' style='grid-template-columns:1fr 1fr 1fr;'><div class='panel'><div class='panel-head'><h3>Sales Funnel</h3></div><p>New Lead <b style='float:right;color:#A855F7;'>{total}</b></p><p>Qualified <b style='float:right;color:#1683FF;'>{qualified}</b></p><p>Website Sent <b style='float:right;color:#F97316;'>{website_sent}</b></p><p>Hot Leads <b style='float:right;color:#22C55E;'>{hot_leads}</b></p></div><div class='panel'><div class='panel-head'><h3>Team Overview</h3></div><p>Assigned Leads <b style='float:right;color:#22C55E;'>{assigned_leads}</b></p><p>Unassigned <b style='float:right;color:#F97316;'>{total-assigned_leads}</b></p><p>Open Tasks <b style='float:right;color:#EC4899;'>{open_tasks}</b></p><p>Upcoming Follow-ups <b style='float:right;color:#1683FF;'>{upcoming_followups}</b></p></div><div class='panel'><div class='panel-head'><h3>Lead Split</h3></div><p>Wholesaler <b style='float:right;color:#A855F7;'>{wholesalers}</b></p><p>Retailer <b style='float:right;color:#1683FF;'>{retailers}</b></p><p>Personal <b style='float:right;color:#22C55E;'>{personal}</b></p><p>Hot Leads <b style='float:right;color:#F97316;'>{hot_leads}</b></p></div></section>
    <section class='panel'><div class='panel-head'><h3>CRM Leads</h3><a class='view' href='/dashboard?key={esc(DASHBOARD_KEY)}'>Reset</a></div><div class='filters'>{filter_link('All','all')}{filter_link('Wholesaler','wholesaler')}{filter_link('Qualified','qualified')}{filter_link('Hot','hot')}{filter_link('Today Follow-up','followup_today')}{filter_link('Missed','followup_missed')}{filter_link('Assigned','assigned')}{filter_link('Unassigned','unassigned')}{filter_link('Tasks','tasks_open')}</div><table><thead><tr><th>Phone</th><th>Buyer</th><th>Status</th><th>Assigned</th><th>Last Message</th><th>Msg</th><th>Last Seen</th></tr></thead><tbody>{rows_html}</tbody></table></section>
    <section class='bottom-status' style='margin-top:16px;'><div class='status-card'><div class='status-icon'>☘</div><div><b>WhatsApp API</b><small>Connected</small></div></div><div class='status-card'><div class='status-icon'>AI</div><div><b>AI Services</b><small>Active</small></div></div><div class='status-card'><div class='status-icon'>▣</div><div><b>Database</b><small>JSON store active</small></div></div><div class='status-card'><div class='status-icon'>☁</div><div><b>Last Backup</b><small>Use Backup Center</small></div></div><div class='status-card'><div class='status-icon'>⚡</div><div><b>System</b><small>All systems operational</small></div></div></section>
    </main></div></body></html>"""
    return HTMLResponse(content=html)


# ── Export CRM Leads as CSV ───────────────────────────────────────────────────
@app.get("/dashboard/export")
async def export_dashboard(key: str = ""):
    if key != DASHBOARD_KEY:
        return JSONResponse(content={"error": "Access denied"}, status_code=401)

    customers = _load_customers()
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Phone Number",
        "Buyer Type",
        "Lead Status",
        "Assigned To",
        "Assigned At",
        "Pipeline Stage",
        "Pipeline Updated At",
        "Task Text",
        "Task Status",
        "Task Due At",
        "Last Message",
        "Message Count",
        "First Seen",
        "Last Seen",
        "Follow-up At",
        "Follow-up Note",
        "Follow-up Done",
        "Last Follow-up Sent At",
        "Follow-up Sent Count",
    ])

    for c in sorted(customers.values(), key=lambda x: x.get("last_seen", ""), reverse=True):
        writer.writerow([
            c.get("phone_number", ""),
            c.get("buyer_type", ""),
            c.get("lead_status", ""),
            c.get("assigned_to", ""),
            c.get("assigned_at", ""),
            c.get("pipeline_stage", ""),
            c.get("pipeline_updated_at", ""),
            c.get("task_text", ""),
            c.get("task_status", ""),
            c.get("task_due_at", ""),
            c.get("last_message", ""),
            c.get("message_count", ""),
            c.get("first_seen", ""),
            c.get("last_seen", ""),
            c.get("followup_at", ""),
            c.get("followup_note", ""),
            c.get("followup_done", ""),
            c.get("last_followup_sent_at", ""),
            c.get("followup_sent_count", ""),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=rh_leads.csv"},
    )


# ── Customer Profile Page ─────────────────────────────────────────────────────
@app.get("/customer/{phone}", response_class=HTMLResponse)
async def customer_profile(phone: str, key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="<h2 style='font-family:Arial;padding:40px;'>Access Denied</h2>", status_code=401)

    customers = _load_customers()
    customer = customers.get(phone)

    if not customer:
        return HTMLResponse(content=f"<h2 style='font-family:Arial;padding:40px;'>Customer not found: {phone}</h2>", status_code=404)

    def esc(value):
        if value is None:
            return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")

    all_messages = _load_messages()
    customer_messages = [m for m in all_messages if _customer_message_filter(m, phone)]

    msg_html = ""
    for m in customer_messages[-100:]:
        direction = "OUT" if m.get("direction") == "outbound" else "IN"
        msg_class = "msg outbound" if m.get("direction") == "outbound" else "msg"
        msg_html += f"""
        <div class="{msg_class}">
            <div class="msg-time">{esc(direction)} • {esc(m.get("received_at"))} • {esc(m.get("type"))}</div>
            <div class="msg-body">{esc(m.get("body"))}</div>
        </div>
        """

    if not msg_html:
        msg_html = '<div class="empty">No message history found yet.</div>'

    html = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Customer Profile - {esc(phone)}</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f7f7f7; margin:0; padding:24px; color:#111; }}
            .top {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; gap:12px; flex-wrap:wrap; }}
            a.btn, button {{ background:#111; color:white; padding:10px 14px; border-radius:10px; text-decoration:none; border:0; cursor:pointer; }}
            .grid {{ display:grid; grid-template-columns:340px 1fr; gap:18px; }}
            .card {{ background:white; border:1px solid #e5e5e5; border-radius:14px; padding:18px; box-shadow:0 2px 8px rgba(0,0,0,.04); }}
            .label {{ color:#666; font-size:13px; margin-top:12px; }}
            .value {{ font-weight:700; margin-top:4px; word-break:break-word; }}
            .pill {{ display:inline-block; padding:6px 10px; border-radius:999px; background:#e8f0ff; font-size:13px; font-weight:700; }}
            .assigned {{ background:#f3e8ff; color:#6b21a8; }}
            .pipeline {{ background:#e0f2fe; color:#075985; }}
            .task {{ background:#fef3c7; color:#92400e; }}
            textarea {{ width:100%; min-height:140px; padding:12px; border:1px solid #ddd; border-radius:10px; font-size:14px; box-sizing:border-box; }}
            .msg {{ background:#fff; border:1px solid #eee; border-radius:12px; padding:12px; margin-bottom:10px; }}
            .msg.outbound {{ background:#f0fdf4; border-color:#bbf7d0; }}
            .msg-time {{ color:#777; font-size:12px; margin-bottom:6px; }}
            .msg-body {{ font-size:15px; white-space:pre-wrap; }}
            .empty {{ background:white; padding:20px; border-radius:12px; color:#777; text-align:center; }}
            @media(max-width:800px) {{ body {{ padding:14px; }} .grid {{ grid-template-columns:1fr; }} }}
        </style>
    </head>
    <body>
        <div class="top">
            <div>
                <h1>Customer Profile</h1>
                <div>{esc(phone)}</div>
            </div>
            <div>
                <a class="btn" href="/dashboard?key={esc(DASHBOARD_KEY)}">Back to Dashboard</a>
                <a class="btn" href="/customer/{esc(phone)}/timeline?key={esc(DASHBOARD_KEY)}">Timeline</a>
                <a class="btn" href="https://wa.me/{esc(phone)}" target="_blank">Open WhatsApp</a>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <h2>Lead Details</h2>
                <div class="label">Phone</div><div class="value">{esc(customer.get("phone_number"))}</div>
                <div class="label">Buyer Type</div><div class="value"><span class="pill">{esc(customer.get("buyer_type") or "unknown")}</span></div>
                <div class="label">Lead Status</div><div class="value">{esc(customer.get("lead_status"))}</div>
                <div class="label">Assigned To</div><div class="value"><span class="pill assigned">{esc(customer.get("assigned_to") or "Unassigned")}</span></div>
                <div class="label">Pipeline Stage</div><div class="value"><span class="pill">{esc(customer.get("pipeline_stage") or "NEW")}</span></div>
                <div class="label">Task</div><div class="value">{esc(customer.get("task_text") or "No task")}</div>
                <div class="label">Task Status</div><div class="value">{esc(customer.get("task_status") or "")}</div>
                <div class="label">Task Due</div><div class="value">{esc(customer.get("task_due_at") or "")}</div>
                <div class="label">Last Message</div><div class="value">{esc(customer.get("last_message"))}</div>
                <div class="label">Message Count</div><div class="value">{esc(customer.get("message_count"))}</div>
                <div class="label">First Seen</div><div class="value">{esc(customer.get("first_seen"))}</div>
                <div class="label">Last Seen</div><div class="value">{esc(customer.get("last_seen"))}</div>
                <div class="label">Follow-up</div><div class="value">{esc(_format_followup(customer.get("followup_at")) or "Not set")}</div>
                <div class="label">Follow-up Status</div><div class="value">{esc(_followup_status(customer).upper())}</div>
                <div class="label">Last Follow-up Sent</div><div class="value">{esc(customer.get("last_followup_sent_at") or "Not sent")}</div>
                <div class="label">Follow-up Sent Count</div><div class="value">{esc(customer.get("followup_sent_count") or 0)}</div>

                <hr style="margin:18px 0;border:0;border-top:1px solid #eee;">
                <h3>Lead Controls</h3>
                <form method="post" action="/customer/{esc(phone)}/status?key={esc(DASHBOARD_KEY)}">
                    <select name="lead_status" style="width:100%;padding:12px;border:1px solid #ddd;border-radius:10px;">
                        <option value="WAITING_BUYER_TYPE">WAITING_BUYER_TYPE</option>
                        <option value="WAITING_DESIGN">WAITING_DESIGN</option>
                        <option value="WAITING_MOQ">WAITING_MOQ</option>
                        <option value="QUALIFIED_LEAD">QUALIFIED_LEAD</option>
                        <option value="WEBSITE_SENT">WEBSITE_SENT</option>
                        <option value="FOLLOW_UP">FOLLOW_UP</option>
                        <option value="FOLLOW_UP_SENT">FOLLOW_UP_SENT</option>
                        <option value="ORDER_POSSIBLE">ORDER_POSSIBLE</option>
                        <option value="CLOSED">CLOSED</option>
                    </select>
                    <br><br><button type="submit">Update Status</button>
                </form>

                <br>
                <form method="post" action="/customer/{esc(phone)}/hot?key={esc(DASHBOARD_KEY)}">
                    <input type="hidden" name="is_hot_lead" value="{'' if customer.get('is_hot_lead') else 'true'}">
                    <button type="submit">{'Remove Hot Lead ⭐' if customer.get('is_hot_lead') else 'Mark Hot Lead ⭐'}</button>
                </form>

                <hr style="margin:18px 0;border:0;border-top:1px solid #eee;">

                
                <hr style="margin:18px 0;border:0;border-top:1px solid #eee;">
                <h3>Lead Assignment</h3>
                <form method="post" action="/customer/{esc(phone)}/assign?key={esc(DASHBOARD_KEY)}">
                    <select name="assigned_to" style="width:100%;padding:12px;border:1px solid #ddd;border-radius:10px;">
                        <option value="">Unassigned</option>
                        {"".join(f'<option value="{esc(name)}" {"selected" if customer.get("assigned_to") == name else ""}>{esc(name)}</option>' for name in ASSIGNEES)}
                    </select>
                    <br><br><button type="submit">Save Assignment</button>
                </form>

                <hr style="margin:18px 0;border:0;border-top:1px solid #eee;">
                <h3>Sales Pipeline</h3>
                <form method="post" action="/customer/{esc(phone)}/pipeline?key={esc(DASHBOARD_KEY)}">
                    <select name="pipeline_stage" style="width:100%;padding:12px;border:1px solid #ddd;border-radius:10px;">
                        {"".join(f'<option value="{esc(stage)}" {"selected" if (customer.get("pipeline_stage") or "NEW") == stage else ""}>{esc(stage)}</option>' for stage in PIPELINE_STAGES)}
                    </select>
                    <br><br><button type="submit">Update Pipeline</button>
                </form>

                <h3>Task Management</h3>
                <form method="post" action="/customer/{esc(phone)}/task?key={esc(DASHBOARD_KEY)}">
                    <textarea name="task_text" placeholder="Example: Call customer, send catalogue, prepare quote..." style="min-height:85px;">{esc(customer.get("task_text") or "")}</textarea>
                    <label class="label">Task Due Date & Time</label>
                    <input type="datetime-local" name="task_due_at" value="{esc((customer.get("task_due_at") or "")[:16])}" style="width:100%;padding:12px;border:1px solid #ddd;border-radius:10px;box-sizing:border-box;">
                    <label class="label">Task Status</label>
                    <select name="task_status" style="width:100%;padding:12px;border:1px solid #ddd;border-radius:10px;">
                        {"".join(f'<option value="{esc(st)}" {"selected" if (customer.get("task_status") or "OPEN") == st else ""}>{esc(st)}</option>' for st in TASK_STATUSES)}
                    </select>
                    <br><br>
                    <button type="submit" name="action" value="save">Save Task</button>
                    <button type="submit" name="action" value="done" style="background:#166534;">Mark Done</button>
                    <button type="submit" name="action" value="clear" style="background:#991b1b;">Clear</button>
                </form>

                <h3>Follow-up Reminder</h3>
                <form method="post" action="/customer/{esc(phone)}/followup?key={esc(DASHBOARD_KEY)}">
                    <label class="label">Date & Time</label>
                    <input type="datetime-local" name="followup_at" value="{esc((customer.get("followup_at") or "")[:16])}" style="width:100%;padding:12px;border:1px solid #ddd;border-radius:10px;box-sizing:border-box;">
                    <label class="label">Reminder Note</label>
                    <textarea name="followup_note" placeholder="Example: Call for MOQ confirmation / Send catalogue / Ask design screenshot..." style="min-height:90px;">{esc(customer.get("followup_note") or "")}</textarea>
                    <br><br>
                    <button type="submit" name="action" value="save">Save Follow-up</button>
                    <button type="submit" name="action" value="done" style="background:#166534;">Mark Done</button>
                    <button type="submit" name="action" value="clear" style="background:#991b1b;">Clear</button>
                </form>

                <h3>Quick Reply Templates</h3>
                <form method="post" action="/customer/{esc(phone)}/send-template?key={esc(DASHBOARD_KEY)}">
                    <select name="template_key" style="width:100%;padding:12px;border:1px solid #ddd;border-radius:10px;">
                        {"".join(f'<option value="{esc(k)}">{esc(k.title())}</option>' for k in QUICK_REPLY_TEMPLATES.keys())}
                    </select>
                    <br><br><button type="submit" style="background:#1d4ed8;">Send Selected Template</button>
                </form>

                <h3>Send Manual Follow-up</h3>
                <form method="post" action="/customer/{esc(phone)}/send-followup?key={esc(DASHBOARD_KEY)}">
                    <textarea name="message" placeholder="Write follow-up WhatsApp message..." style="min-height:130px;">{esc(customer.get("followup_message_template") or MSG_FOLLOWUP_WHOLESALER)}</textarea>
                    <br><br><button type="submit" style="background:#1d4ed8;">Send WhatsApp Follow-up</button>
                </form>

                <hr style="margin:18px 0;border:0;border-top:1px solid #eee;">
                <h3>Internal Notes</h3>
                <form method="post" action="/customer/{esc(phone)}/notes?key={esc(DASHBOARD_KEY)}">
                    <textarea name="notes" placeholder="Add customer notes here...">{esc(customer.get("notes") or "")}</textarea>
                    <br><br><button type="submit">Save Notes</button>
                </form>
            </div>

            <div class="card">
                <h2>Message History</h2>
                {msg_html}
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/customer/{phone}/notes")
async def save_customer_notes(phone: str, key: str = "", notes: str = Form("")):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)

    customers = _load_customers()
    if phone not in customers:
        return HTMLResponse(content="Customer not found", status_code=404)

    customers[phone]["notes"] = notes
    customers[phone]["notes_updated_at"] = datetime.utcnow().isoformat() + "Z"
    _save_customers(customers)

    return RedirectResponse(url=f"/customer/{phone}?key={DASHBOARD_KEY}", status_code=303)



@app.post("/customer/{phone}/status")
async def update_customer_status(phone: str, key: str = "", lead_status: str = Form("")):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)

    customers = _load_customers()
    if phone not in customers:
        return HTMLResponse(content="Customer not found", status_code=404)

    customers[phone]["lead_status"] = lead_status
    customers[phone]["status_updated_at"] = datetime.utcnow().isoformat() + "Z"
    _save_customers(customers)

    return RedirectResponse(url=f"/customer/{phone}?key={DASHBOARD_KEY}", status_code=303)


@app.post("/customer/{phone}/hot")
async def update_hot_lead(phone: str, key: str = "", is_hot_lead: str = Form("")):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)

    customers = _load_customers()
    if phone not in customers:
        return HTMLResponse(content="Customer not found", status_code=404)

    customers[phone]["is_hot_lead"] = True if is_hot_lead == "true" else False
    customers[phone]["hot_lead_updated_at"] = datetime.utcnow().isoformat() + "Z"
    _save_customers(customers)

    return RedirectResponse(url=f"/customer/{phone}?key={DASHBOARD_KEY}", status_code=303)



@app.post("/customer/{phone}/assign")
async def assign_customer_lead(phone: str, key: str = "", assigned_to: str = Form("")):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)

    customers = _load_customers()
    if phone not in customers:
        return HTMLResponse(content="Customer not found", status_code=404)

    clean_assignee = (assigned_to or "").strip()
    now = datetime.utcnow().isoformat() + "Z"

    if clean_assignee:
        customers[phone]["assigned_to"] = clean_assignee
        customers[phone]["assigned_at"] = now
    else:
        customers[phone].pop("assigned_to", None)
        customers[phone].pop("assigned_at", None)
        customers[phone]["unassigned_at"] = now

    customers[phone]["assignment_updated_at"] = now
    _save_customers(customers)

    return RedirectResponse(url=f"/customer/{phone}?key={DASHBOARD_KEY}", status_code=303)


@app.post("/customer/{phone}/followup")
async def update_customer_followup(
    phone: str,
    key: str = "",
    followup_at: str = Form(""),
    followup_note: str = Form(""),
    action: str = Form("save"),
):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)

    customers = _load_customers()
    if phone not in customers:
        return HTMLResponse(content="Customer not found", status_code=404)

    now = datetime.utcnow().isoformat() + "Z"

    if action == "clear":
        customers[phone].pop("followup_at", None)
        customers[phone].pop("followup_note", None)
        customers[phone]["followup_done"] = False
        customers[phone]["followup_updated_at"] = now
    elif action == "done":
        customers[phone]["followup_done"] = True
        customers[phone]["followup_done_at"] = now
        customers[phone]["followup_updated_at"] = now
    else:
        customers[phone]["followup_at"] = followup_at
        customers[phone]["followup_note"] = followup_note
        customers[phone]["followup_done"] = False
        customers[phone]["followup_updated_at"] = now
        if customers[phone].get("lead_status") not in ("QUALIFIED_LEAD", "ORDER_POSSIBLE", "CLOSED"):
            customers[phone]["lead_status"] = "FOLLOW_UP"

    _save_customers(customers)
    return RedirectResponse(url=f"/customer/{phone}?key={DASHBOARD_KEY}", status_code=303)




@app.post("/customer/{phone}/send-followup")
async def send_customer_followup(phone: str, key: str = "", message: str = Form("")):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)

    customers = _load_customers()
    if phone not in customers:
        return HTMLResponse(content="Customer not found", status_code=404)

    clean_message = (message or "").strip()
    if not clean_message:
        return HTMLResponse(content="Message cannot be empty", status_code=400)

    success = await whatsapp.send_text_message(to=phone, body=clean_message)
    now = datetime.utcnow().isoformat() + "Z"

    if success:
        customers[phone]["last_followup_sent_at"] = now
        customers[phone]["followup_sent_count"] = int(customers[phone].get("followup_sent_count") or 0) + 1
        customers[phone]["followup_message_template"] = clean_message
        customers[phone]["followup_done"] = True
        customers[phone]["followup_done_at"] = now
        customers[phone]["lead_status"] = "FOLLOW_UP_SENT"
        _save_customers(customers)
        _append_outbound_message(phone=phone, body=clean_message)
        logger.info("✅ Manual follow-up sent | to=%s", phone)
    else:
        customers[phone]["last_followup_failed_at"] = now
        customers[phone]["last_followup_failed_message"] = clean_message
        _save_customers(customers)
        logger.warning("⚠️ Manual follow-up failed | to=%s", phone)

    return RedirectResponse(url=f"/customer/{phone}?key={DASHBOARD_KEY}", status_code=303)



@app.post("/customer/{phone}/pipeline")
async def update_customer_pipeline(phone: str, key: str = "", pipeline_stage: str = Form("NEW")):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers = _load_customers()
    if phone not in customers:
        return HTMLResponse(content="Customer not found", status_code=404)
    stage = (pipeline_stage or "NEW").strip().upper()
    if stage not in PIPELINE_STAGES:
        stage = "NEW"
    customers[phone]["pipeline_stage"] = stage
    customers[phone]["pipeline_updated_at"] = datetime.utcnow().isoformat() + "Z"
    if stage == "QUALIFIED":
        customers[phone]["lead_status"] = "QUALIFIED_LEAD"
    elif stage == "QUOTE_SENT":
        customers[phone]["lead_status"] = "QUOTE_SENT"
    elif stage == "ORDER_CONFIRMED":
        customers[phone]["lead_status"] = "ORDER_POSSIBLE"
    elif stage in ("CLOSED", "LOST"):
        customers[phone]["lead_status"] = "CLOSED"
    _save_customers(customers)
    return RedirectResponse(url=f"/customer/{phone}?key={DASHBOARD_KEY}", status_code=303)


@app.post("/customer/{phone}/task")
async def update_customer_task(
    phone: str,
    key: str = "",
    task_text: str = Form(""),
    task_due_at: str = Form(""),
    task_status: str = Form("OPEN"),
    action: str = Form("save"),
):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers = _load_customers()
    if phone not in customers:
        return HTMLResponse(content="Customer not found", status_code=404)
    now = datetime.utcnow().isoformat() + "Z"
    if action == "clear":
        for field in ("task_text", "task_due_at", "task_status", "task_done_at"):
            customers[phone].pop(field, None)
        customers[phone]["task_updated_at"] = now
    elif action == "done":
        customers[phone]["task_status"] = "DONE"
        customers[phone]["task_done_at"] = now
        customers[phone]["task_updated_at"] = now
    else:
        customers[phone]["task_text"] = (task_text or "").strip()
        customers[phone]["task_due_at"] = task_due_at
        status = (task_status or "OPEN").strip().upper()
        customers[phone]["task_status"] = status if status in TASK_STATUSES else "OPEN"
        customers[phone]["task_updated_at"] = now
    _save_customers(customers)
    return RedirectResponse(url=f"/customer/{phone}?key={DASHBOARD_KEY}", status_code=303)


@app.post("/customer/{phone}/send-template")
async def send_customer_template(phone: str, key: str = "", template_key: str = Form("")):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers = _load_customers()
    if phone not in customers:
        return HTMLResponse(content="Customer not found", status_code=404)
    clean_key = (template_key or "").strip()
    message = QUICK_REPLY_TEMPLATES.get(clean_key)
    if not message:
        return HTMLResponse(content="Template not found", status_code=404)
    success = await whatsapp.send_text_message(to=phone, body=message)
    now = datetime.utcnow().isoformat() + "Z"
    if success:
        customers[phone]["last_template_sent"] = clean_key
        customers[phone]["last_template_sent_at"] = now
        customers[phone]["template_sent_count"] = int(customers[phone].get("template_sent_count") or 0) + 1
        _save_customers(customers)
        _append_outbound_message(phone=phone, body=message)
    else:
        customers[phone]["last_template_failed_at"] = now
        customers[phone]["last_template_failed"] = clean_key
        _save_customers(customers)
    return RedirectResponse(url=f"/customer/{phone}?key={DASHBOARD_KEY}", status_code=303)


# ── v1.6 Customer Timeline ───────────────────────────────────────────────────
@app.get("/customer/{phone}/timeline", response_class=HTMLResponse)
async def customer_timeline(phone: str, key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers = _load_customers()
    customer = customers.get(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)

    def esc(value):
        if value is None:
            return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")

    events = []
    for field, label in [
        ("first_seen", "Lead created"), ("last_seen", "Last activity"),
        ("assigned_at", "Lead assigned"), ("unassigned_at", "Lead unassigned"),
        ("status_updated_at", "Status updated"), ("pipeline_updated_at", "Pipeline updated"),
        ("notes_updated_at", "Notes updated"), ("followup_updated_at", "Follow-up updated"),
        ("followup_done_at", "Follow-up marked done"), ("last_followup_sent_at", "Follow-up WhatsApp sent"),
        ("task_updated_at", "Task updated"), ("task_done_at", "Task completed"),
        ("last_template_sent_at", "Quick reply sent"), ("hot_lead_updated_at", "Hot lead updated"),
    ]:
        if customer.get(field):
            events.append({"at": customer.get(field), "type": label, "detail": field})

    for m in _load_messages():
        if _customer_message_filter(m, phone):
            direction = "Outbound" if m.get("direction") == "outbound" or m.get("from") == "RH_BUSINESS_OS" else "Inbound"
            events.append({"at": m.get("received_at") or m.get("timestamp"), "type": f"{direction} message", "detail": m.get("body")})

    events = sorted(events, key=lambda x: str(x.get("at") or ""), reverse=True)[:200]
    rows = "".join(f"""
        <div class='event'>
            <div class='time'>{esc(e.get('at'))}</div>
            <div class='etype'>{esc(e.get('type'))}</div>
            <div class='detail'>{esc(e.get('detail'))}</div>
        </div>
    """ for e in events) or "<div class='empty'>No timeline activity yet.</div>"

    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
    <title>Timeline - {esc(phone)}</title><style>
    body{{font-family:Arial;background:#f7f7f7;padding:24px;color:#111}} .wrap{{max-width:900px;margin:auto}}
    .top{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}} a.btn{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none}}
    .event{{background:white;border:1px solid #e5e5e5;border-radius:14px;padding:14px;margin:10px 0;box-shadow:0 2px 8px rgba(0,0,0,.04)}}
    .time{{color:#777;font-size:12px;margin-bottom:6px}} .etype{{font-weight:700;margin-bottom:6px}} .detail{{white-space:pre-wrap;color:#333}}
    .empty{{background:white;padding:24px;border-radius:14px;text-align:center;color:#777}}
    </style></head><body><div class='wrap'><div class='top'><div><h1>Customer Timeline</h1><div>{esc(phone)}</div></div>
    <a class='btn' href='/customer/{esc(phone)}?key={esc(DASHBOARD_KEY)}'>Back to Profile</a></div>{rows}</div></body></html>
    """)


# ── v1.7 Follow-up Calendar ──────────────────────────────────────────────────
@app.get("/calendar", response_class=HTMLResponse)
async def followup_calendar(key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)

    def esc(value):
        if value is None:
            return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")

    rows = []
    for c in _load_customers().values():
        if c.get("followup_at") and c.get("followup_done") is not True:
            rows.append({"type":"Follow-up", "due":c.get("followup_at"), "phone":c.get("phone_number"), "assigned":c.get("assigned_to") or "Unassigned", "note":c.get("followup_note") or c.get("last_message") or ""})
        if c.get("task_due_at") and c.get("task_status") != "DONE":
            rows.append({"type":"Task", "due":c.get("task_due_at"), "phone":c.get("phone_number"), "assigned":c.get("assigned_to") or "Unassigned", "note":c.get("task_text") or ""})
    rows.sort(key=lambda x: str(x.get("due") or ""))
    body = "".join(f"""<tr><td>{esc(r['due'])}</td><td>{esc(r['type'])}</td><td><a href='/customer/{esc(r['phone'])}?key={esc(DASHBOARD_KEY)}'>{esc(r['phone'])}</a></td><td>{esc(r['assigned'])}</td><td>{esc(r['note'])}</td></tr>""" for r in rows) or "<tr><td colspan='5' style='text-align:center;color:#777;padding:30px'>No pending follow-ups or tasks.</td></tr>"
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Follow-up Calendar</title>
    <style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} .top{{display:flex;justify-content:space-between;align-items:center}} a.btn{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none}} table{{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden}} th,td{{padding:12px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}} th{{background:#111;color:white}}</style></head>
    <body><div class='top'><h1>Follow-up Calendar</h1><a class='btn' href='/dashboard?key={esc(DASHBOARD_KEY)}'>Back</a></div><table><thead><tr><th>Due</th><th>Type</th><th>Customer</th><th>Assigned</th><th>Note</th></tr></thead><tbody>{body}</tbody></table></body></html>
    """)


# ── v1.8 Team Dashboard ──────────────────────────────────────────────────────
@app.get("/team", response_class=HTMLResponse)
async def team_dashboard(key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)

    def esc(value):
        if value is None:
            return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")

    customers = list(_load_customers().values())
    names = ASSIGNEES + ["Unassigned"]
    rows = ""
    for name in names:
        member = [c for c in customers if (c.get("assigned_to") or "Unassigned") == name]
        hot = sum(1 for c in member if c.get("is_hot_lead") is True)
        open_tasks = sum(1 for c in member if c.get("task_text") and c.get("task_status") != "DONE")
        missed = sum(1 for c in member if _followup_status(c) == "missed")
        qualified = sum(1 for c in member if c.get("lead_status") == "QUALIFIED_LEAD")
        orders = sum(1 for c in member if c.get("pipeline_stage") == "ORDER_CONFIRMED")
        filter_key = "unassigned" if name == "Unassigned" else "assigned_" + name.lower()
        rows += f"<tr><td><a href='/dashboard?key={esc(DASHBOARD_KEY)}&filter={esc(filter_key)}'>{esc(name)}</a></td><td>{len(member)}</td><td>{hot}</td><td>{open_tasks}</td><td>{missed}</td><td>{qualified}</td><td>{orders}</td></tr>"
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Team Dashboard</title>
    <style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} .top{{display:flex;justify-content:space-between;align-items:center}} a.btn{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none}} table{{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden}} th,td{{padding:12px;border-bottom:1px solid #eee;text-align:left}} th{{background:#111;color:white}}</style></head>
    <body><div class='top'><h1>Team Dashboard</h1><a class='btn' href='/dashboard?key={esc(DASHBOARD_KEY)}'>Back</a></div><table><thead><tr><th>Team Member</th><th>Total Leads</th><th>Hot</th><th>Open Tasks</th><th>Missed Follow-ups</th><th>Qualified</th><th>Orders</th></tr></thead><tbody>{rows}</tbody></table></body></html>
    """)


# ── v2.5 Backup & Restore ────────────────────────────────────────────────────
@app.get("/backup", response_class=HTMLResponse)
async def backup_page(key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    def esc(value):
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Backup & Restore</title>
    <style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} .card{{background:white;padding:20px;border-radius:14px;border:1px solid #e5e5e5;max-width:700px}} a.btn,button{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none;border:0;cursor:pointer}} input{{padding:12px;border:1px solid #ddd;border-radius:10px}}</style></head>
    <body><div class='card'><h1>Backup & Restore</h1><p>Download full JSON backup of customers, sessions and messages.</p><p><a class='btn' href='/backup/download?key={esc(DASHBOARD_KEY)}'>Download Backup ZIP</a> <a class='btn' href='/dashboard?key={esc(DASHBOARD_KEY)}'>Back</a></p><hr><h3>Restore customers.json only</h3><p style='color:#777'>Safety: restore only replaces customers.json. Sessions/messages remain safe.</p><form method='post' enctype='multipart/form-data' action='/backup/restore-customers?key={esc(DASHBOARD_KEY)}'><input type='file' name='file' accept='.json' required> <button type='submit'>Restore Customers</button></form></div></body></html>
    """)

@app.get("/backup/download")
async def download_backup(key: str = ""):
    if key != DASHBOARD_KEY:
        return JSONResponse(content={"error":"Access denied"}, status_code=401)
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, arc in [(CUSTOMERS_FILE, "customers.json"), (SESSIONS_FILE, "sessions.json"), (MESSAGES_FILE, "messages.json")]:
            if os.path.exists(path):
                zf.write(path, arc)
            else:
                zf.writestr(arc, "{}" if arc != "messages.json" else "[]")
        zf.writestr("backup_info.json", json.dumps({"created_at": datetime.utcnow().isoformat()+"Z", "version":"2.5.0"}, indent=2))
    mem.seek(0)
    return StreamingResponse(mem, media_type="application/zip", headers={"Content-Disposition":"attachment; filename=rh_business_os_backup_v19.zip"})

@app.post("/backup/restore-customers")
async def restore_customers_backup(key: str = "", file: UploadFile = File(...)):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    raw = await file.read()
    try:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("customers.json must be an object keyed by phone number")
    except Exception as exc:
        return HTMLResponse(content=f"Invalid JSON backup: {exc}", status_code=400)
    os.makedirs(os.path.dirname(CUSTOMERS_FILE), exist_ok=True)
    if os.path.exists(CUSTOMERS_FILE):
        safety = CUSTOMERS_FILE + ".before_restore_" + datetime.utcnow().strftime("%Y%m%d%H%M%S")
        with open(CUSTOMERS_FILE, "rb") as src, open(safety, "wb") as dst:
            dst.write(src.read())
    with open(CUSTOMERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return RedirectResponse(url=f"/dashboard?key={DASHBOARD_KEY}", status_code=303)



# ── v2.0 to v2.5 Quotation System ────────────────────────────────────────────
PRICE_LIST_FILE = os.getenv("PRICE_LIST_FILE", "data/price_list.json")
DEFAULT_PRICE_LIST = {
    "Rhinestone Transfer Sticker": {"unit": "pcs", "price": 0.0},
    "Custom Rhinestone Design": {"unit": "design", "price": 0.0},
    "Rhinestone Shirt": {"unit": "pcs", "price": 0.0},
    "Job Work Pasting": {"unit": "pcs", "price": 0.0},
}

def _money(value) -> str:
    try:
        return f"₹{float(value):,.2f}"
    except Exception:
        return "₹0.00"

def _load_price_list() -> dict:
    if not os.path.exists(PRICE_LIST_FILE):
        return DEFAULT_PRICE_LIST.copy()
    try:
        with open(PRICE_LIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else DEFAULT_PRICE_LIST.copy()
    except Exception as exc:
        logger.error("Failed to load price list: %s", exc)
        return DEFAULT_PRICE_LIST.copy()

def _save_price_list(data: dict) -> None:
    os.makedirs(os.path.dirname(PRICE_LIST_FILE), exist_ok=True)
    with open(PRICE_LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _quote_total(q: dict) -> dict:
    qty = float(q.get("qty") or 0)
    unit_price = float(q.get("unit_price") or 0)
    discount = float(q.get("discount") or 0)
    subtotal = qty * unit_price
    total = max(subtotal - discount, 0)
    q["subtotal"] = subtotal
    q["total"] = total
    return q

def _get_customer_or_404(phone: str):
    customers = _load_customers()
    if phone not in customers:
        return customers, None
    return customers, customers[phone]

def _find_quote(customer: dict, quote_id: str):
    for q in customer.get("quotes", []):
        if str(q.get("quote_id")) == str(quote_id):
            return q
    return None

@app.get("/price-list", response_class=HTMLResponse)
async def price_list_page(key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    def esc(value):
        if value is None: return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")
    plist = _load_price_list()
    rows = ""
    for name, item in plist.items():
        rows += f"""
        <tr><td><input name='name' value='{esc(name)}'></td><td><input name='unit' value='{esc(item.get('unit','pcs'))}'></td><td><input name='price' type='number' step='0.01' value='{esc(item.get('price',0))}'></td></tr>
        """
    rows += "<tr><td><input name='name' placeholder='New item'></td><td><input name='unit' value='pcs'></td><td><input name='price' type='number' step='0.01' value='0'></td></tr>"
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Price List</title>
    <style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} .top{{display:flex;justify-content:space-between;align-items:center}} a.btn,button{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none;border:0}} table{{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden}} th,td{{padding:12px;border-bottom:1px solid #eee;text-align:left}} th{{background:#111;color:white}} input{{width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;box-sizing:border-box}}</style></head>
    <body><div class='top'><h1>Price List</h1><a class='btn' href='/dashboard?key={esc(DASHBOARD_KEY)}'>Back</a></div><form method='post' action='/price-list/update?key={esc(DASHBOARD_KEY)}'><table><thead><tr><th>Item</th><th>Unit</th><th>Default Price</th></tr></thead><tbody>{rows}</tbody></table><br><button type='submit'>Save Price List</button></form></body></html>
    """)

@app.post("/price-list/update")
async def update_price_list(key: str = "", name: list[str] = Form([]), unit: list[str] = Form([]), price: list[str] = Form([])):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    data = {}
    for i, n in enumerate(name):
        n = (n or "").strip()
        if not n:
            continue
        u = unit[i].strip() if i < len(unit) and unit[i] else "pcs"
        try: pr = float(price[i]) if i < len(price) else 0.0
        except Exception: pr = 0.0
        data[n] = {"unit": u, "price": pr}
    _save_price_list(data)
    return RedirectResponse(url=f"/price-list?key={DASHBOARD_KEY}", status_code=303)

@app.get("/customer/{phone}/quote/new", response_class=HTMLResponse)
async def new_quote_page(phone: str, key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers, customer = _get_customer_or_404(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)
    def esc(value):
        if value is None: return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")
    plist = _load_price_list()
    options = "".join(f"<option value='{esc(n)}' data-price='{esc(v.get('price',0))}'>{esc(n)} — {_money(v.get('price',0))}/{esc(v.get('unit','pcs'))}</option>" for n,v in plist.items())
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Create Quote</title>
    <style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} .card{{background:white;max-width:760px;padding:20px;border-radius:14px;border:1px solid #e5e5e5}} label{{display:block;margin-top:14px;color:#555}} input,select,textarea{{width:100%;padding:12px;border:1px solid #ddd;border-radius:10px;box-sizing:border-box}} a.btn,button{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none;border:0;cursor:pointer}}</style></head>
    <body><div class='card'><h1>Create Quotation</h1><p>Customer: <b>{esc(phone)}</b></p><form method='post' action='/customer/{esc(phone)}/quote/create?key={esc(DASHBOARD_KEY)}'>
    <label>Product / Service</label><select name='product_name' id='product' onchange='document.getElementById("price").value=this.options[this.selectedIndex].dataset.price'>{options}</select>
    <label>Design / Size / Details</label><input name='details' placeholder='Example: Tiger sticker, 12 inch, SS4 crystal'>
    <label>Quantity</label><input name='qty' type='number' step='1' value='100'>
    <label>Unit Price</label><input id='price' name='unit_price' type='number' step='0.01' value='0'>
    <label>Discount</label><input name='discount' type='number' step='0.01' value='0'>
    <label>Quote Validity Days</label><input name='validity_days' type='number' step='1' value='7'>
    <label>Internal / Customer Notes</label><textarea name='notes' placeholder='Payment, delivery, MOQ, GST, shipping etc.'></textarea><br><br>
    <button type='submit'>Create Quote</button> <a class='btn' href='/customer/{esc(phone)}?key={esc(DASHBOARD_KEY)}'>Cancel</a></form></div></body></html>
    """)

@app.post("/customer/{phone}/quote/create")
async def create_quote(phone: str, key: str = "", product_name: str = Form(""), details: str = Form(""), qty: float = Form(0), unit_price: float = Form(0), discount: float = Form(0), validity_days: int = Form(7), notes: str = Form("")):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers, customer = _get_customer_or_404(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)
    now = datetime.utcnow()
    quote_id = "Q" + now.strftime("%Y%m%d%H%M%S")
    quote = _quote_total({"quote_id": quote_id, "product_name": product_name, "details": details, "qty": qty, "unit_price": unit_price, "discount": discount, "validity_days": validity_days, "valid_until": (now + timedelta(days=int(validity_days or 7))).date().isoformat(), "notes": notes, "status": "DRAFT", "created_at": now.isoformat()+"Z", "sent_at": None})
    customer.setdefault("quotes", []).append(quote)
    customer["last_quote_id"] = quote_id
    customer["last_quote_total"] = quote.get("total")
    customer["lead_status"] = "QUOTE_PENDING"
    customer["pipeline_stage"] = "QUOTE_PENDING"
    _save_customers(customers)
    return RedirectResponse(url=f"/customer/{phone}/quote/{quote_id}?key={DASHBOARD_KEY}", status_code=303)

@app.get("/customer/{phone}/quotes", response_class=HTMLResponse)
async def customer_quotes(phone: str, key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers, customer = _get_customer_or_404(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)
    def esc(value):
        if value is None: return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")
    body = "".join(f"<tr><td><a href='/customer/{esc(phone)}/quote/{esc(q.get('quote_id'))}?key={esc(DASHBOARD_KEY)}'>{esc(q.get('quote_id'))}</a></td><td>{esc(q.get('product_name'))}</td><td>{esc(q.get('qty'))}</td><td>{_money(q.get('total'))}</td><td>{esc(q.get('status'))}</td><td>{esc(q.get('created_at'))}</td></tr>" for q in reversed(customer.get('quotes', []))) or "<tr><td colspan='6' style='text-align:center;padding:24px;color:#777'>No quotes yet.</td></tr>"
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Quote History</title><style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} a.btn{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none}} table{{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden}} th,td{{padding:12px;border-bottom:1px solid #eee;text-align:left}} th{{background:#111;color:white}}</style></head><body><h1>Quote History</h1><p><a class='btn' href='/customer/{esc(phone)}/quote/new?key={esc(DASHBOARD_KEY)}'>New Quote</a> <a class='btn' href='/customer/{esc(phone)}?key={esc(DASHBOARD_KEY)}'>Back</a></p><table><thead><tr><th>Quote ID</th><th>Product</th><th>Qty</th><th>Total</th><th>Status</th><th>Created</th></tr></thead><tbody>{body}</tbody></table></body></html>
    """)

@app.get("/customer/{phone}/quote/{quote_id}", response_class=HTMLResponse)
async def view_quote(phone: str, quote_id: str, key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers, customer = _get_customer_or_404(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)
    q = _find_quote(customer, quote_id)
    if not q:
        return HTMLResponse(content="Quote not found", status_code=404)
    q = _quote_total(q)
    def esc(value):
        if value is None: return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")
    msg = f"Hello, quotation {quote_id} total is {_money(q.get('total'))}. Valid until {q.get('valid_until')}."
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Quotation {esc(quote_id)}</title>
    <style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} .quote{{background:white;max-width:850px;margin:auto;padding:28px;border-radius:14px;border:1px solid #e5e5e5}} .top{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}} table{{width:100%;border-collapse:collapse;margin-top:20px}} th,td{{padding:12px;border-bottom:1px solid #eee;text-align:left}} th{{background:#111;color:white}} .total{{font-size:24px;font-weight:700;text-align:right;margin-top:16px}} a.btn,button{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none;border:0;cursor:pointer}} select{{padding:10px;border:1px solid #ddd;border-radius:10px}} @media print{{.actions{{display:none}} body{{background:white}} .quote{{border:0}}}}</style></head>
    <body><div class='quote'><div class='top'><div><h1>Rhinestone Heritage</h1><p>Quotation: <b>{esc(quote_id)}</b><br>Customer: <b>{esc(phone)}</b><br>Valid Until: <b>{esc(q.get('valid_until'))}</b></p></div><div><b>Status:</b> {esc(q.get('status'))}</div></div>
    <table><thead><tr><th>Product</th><th>Details</th><th>Qty</th><th>Unit Price</th><th>Discount</th><th>Total</th></tr></thead><tbody><tr><td>{esc(q.get('product_name'))}</td><td>{esc(q.get('details'))}</td><td>{esc(q.get('qty'))}</td><td>{_money(q.get('unit_price'))}</td><td>{_money(q.get('discount'))}</td><td>{_money(q.get('total'))}</td></tr></tbody></table>
    <div class='total'>Grand Total: {_money(q.get('total'))}</div><p><b>Notes:</b><br>{esc(q.get('notes'))}</p>
    <div class='actions'><hr><button onclick='window.print()'>Print / Save PDF</button> <a class='btn' href='/customer/{esc(phone)}/quotes?key={esc(DASHBOARD_KEY)}'>Quote History</a> <a class='btn' href='/customer/{esc(phone)}?key={esc(DASHBOARD_KEY)}'>Customer</a><br><br>
    <form style='display:inline' method='post' action='/customer/{esc(phone)}/quote/{esc(quote_id)}/send?key={esc(DASHBOARD_KEY)}'><button type='submit'>Send Quote on WhatsApp</button></form>
    <form style='display:inline' method='post' action='/customer/{esc(phone)}/quote/{esc(quote_id)}/status?key={esc(DASHBOARD_KEY)}'><select name='status'><option>DRAFT</option><option>QUOTE_SENT</option><option>APPROVED</option><option>REJECTED</option><option>EXPIRED</option><option>ORDER_CREATED</option></select><button type='submit'>Update Status</button></form>
    <p style='color:#777'>WhatsApp text preview: {esc(msg)}</p></div></div></body></html>
    """)

@app.post("/customer/{phone}/quote/{quote_id}/status")
async def update_quote_status(phone: str, quote_id: str, key: str = "", status: str = Form("DRAFT")):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers, customer = _get_customer_or_404(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)
    q = _find_quote(customer, quote_id)
    if not q:
        return HTMLResponse(content="Quote not found", status_code=404)
    q["status"] = status
    q["status_updated_at"] = datetime.utcnow().isoformat()+"Z"
    if status == "QUOTE_SENT":
        customer["lead_status"] = "QUOTE_SENT"; customer["pipeline_stage"] = "QUOTE_SENT"
    elif status == "APPROVED":
        customer["lead_status"] = "ORDER_POSSIBLE"; customer["pipeline_stage"] = "ORDER_CONFIRMED"
    elif status == "REJECTED":
        customer["lead_status"] = "FOLLOW_UP"; customer["pipeline_stage"] = "LOST"
    _save_customers(customers)
    return RedirectResponse(url=f"/customer/{phone}/quote/{quote_id}?key={DASHBOARD_KEY}", status_code=303)

@app.post("/customer/{phone}/quote/{quote_id}/send")
async def send_quote_whatsapp(phone: str, quote_id: str, key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers, customer = _get_customer_or_404(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)
    q = _find_quote(customer, quote_id)
    if not q:
        return HTMLResponse(content="Quote not found", status_code=404)
    q = _quote_total(q)
    body = (f"Hello 👋\n\nRhinestone Heritage quotation details:\n\nQuote ID: {quote_id}\nProduct: {q.get('product_name')}\nDetails: {q.get('details')}\nQty: {q.get('qty')}\nTotal: {_money(q.get('total'))}\nValid Until: {q.get('valid_until')}\n\nNotes: {q.get('notes') or '-'}\n\nPlease confirm if we should proceed.\nTeam Rhinestone Heritage")
    await _reply(phone, body)
    q["status"] = "QUOTE_SENT"
    q["sent_at"] = datetime.utcnow().isoformat()+"Z"
    customer["lead_status"] = "QUOTE_SENT"
    customer["pipeline_stage"] = "QUOTE_SENT"
    _append_message({"message_id": f"manual_quote_{quote_id}", "from": "RH_BUSINESS_OS", "to": phone, "timestamp": str(int(datetime.utcnow().timestamp())), "received_at": datetime.utcnow().isoformat()+"Z", "type": "outbound_quote", "body": body, "raw": {"quote_id": quote_id}})
    _save_customers(customers)
    return RedirectResponse(url=f"/customer/{phone}/quote/{quote_id}?key={DASHBOARD_KEY}", status_code=303)

@app.get("/quotes", response_class=HTMLResponse)
async def quotes_dashboard(key: str = "", status: str = "all"):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    def esc(value):
        if value is None: return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")
    rows = []
    for c in _load_customers().values():
        for q in c.get("quotes", []):
            if status == "all" or q.get("status") == status:
                rows.append((c.get("phone_number"), _quote_total(q)))
    rows.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
    total_value = sum(float(q.get("total") or 0) for _, q in rows)
    body = "".join(f"<tr><td><a href='/customer/{esc(phone)}/quote/{esc(q.get('quote_id'))}?key={esc(DASHBOARD_KEY)}'>{esc(q.get('quote_id'))}</a></td><td><a href='/customer/{esc(phone)}?key={esc(DASHBOARD_KEY)}'>{esc(phone)}</a></td><td>{esc(q.get('product_name'))}</td><td>{_money(q.get('total'))}</td><td>{esc(q.get('status'))}</td><td>{esc(q.get('created_at'))}</td></tr>" for phone, q in rows) or "<tr><td colspan='6' style='text-align:center;padding:24px;color:#777'>No quotes found.</td></tr>"
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Quotes Dashboard</title><style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} .top{{display:flex;justify-content:space-between;align-items:center}} a.btn{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none}} .cards{{display:flex;gap:12px;flex-wrap:wrap}} .card{{background:white;padding:16px;border-radius:14px;border:1px solid #e5e5e5}} table{{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden;margin-top:16px}} th,td{{padding:12px;border-bottom:1px solid #eee;text-align:left}} th{{background:#111;color:white}}</style></head><body><div class='top'><h1>Quotes Dashboard</h1><p><a class='btn' href='/dashboard?key={esc(DASHBOARD_KEY)}'>Back</a> <a class='btn' href='/price-list?key={esc(DASHBOARD_KEY)}'>Price List</a></p></div><div class='cards'><div class='card'><b>Total Quotes</b><br>{len(rows)}</div><div class='card'><b>Total Quote Value</b><br>{_money(total_value)}</div></div><p><a href='/quotes?key={esc(DASHBOARD_KEY)}&status=all'>All</a> | <a href='/quotes?key={esc(DASHBOARD_KEY)}&status=DRAFT'>Draft</a> | <a href='/quotes?key={esc(DASHBOARD_KEY)}&status=QUOTE_SENT'>Sent</a> | <a href='/quotes?key={esc(DASHBOARD_KEY)}&status=APPROVED'>Approved</a></p><table><thead><tr><th>Quote</th><th>Customer</th><th>Product</th><th>Total</th><th>Status</th><th>Created</th></tr></thead><tbody>{body}</tbody></table></body></html>
    """)



# ── v2.6 to v3.0 Orders, Invoice, Payment, Production ───────────────────────
ORDER_STATUSES = ["PENDING", "IN_PRODUCTION", "READY", "DISPATCHED", "DELIVERED", "CANCELLED"]
PAYMENT_STATUSES = ["UNPAID", "PARTIAL", "PAID"]
PRODUCTION_PRIORITIES = ["NORMAL", "HIGH", "URGENT"]


def _generate_order_id(customer: dict) -> str:
    count = len(customer.get("orders", [])) + 1
    return f"ORD-{datetime.utcnow().strftime('%Y%m%d')}-{count:03d}"


def _generate_invoice_no(customer: dict) -> str:
    count = sum(1 for o in customer.get("orders", []) if o.get("invoice_no")) + 1
    return f"INV-{datetime.utcnow().strftime('%Y%m%d')}-{count:03d}"


def _order_total(order: dict) -> float:
    try:
        return float(order.get("total_amount") or 0)
    except Exception:
        return 0.0


def _payment_summary(order: dict) -> dict:
    total = _order_total(order)
    paid = 0.0
    for p in order.get("payments", []):
        try:
            paid += float(p.get("amount") or 0)
        except Exception:
            pass
    balance = max(total - paid, 0.0)
    if paid <= 0:
        status = "UNPAID"
    elif balance <= 0:
        status = "PAID"
    else:
        status = "PARTIAL"
    order["amount_paid"] = paid
    order["balance_due"] = balance
    order["payment_status"] = status
    return {"total": total, "paid": paid, "balance": balance, "status": status}


def _find_order(customer: dict, order_id: str):
    for order in customer.get("orders", []):
        if str(order.get("order_id")) == str(order_id):
            return order
    return None


@app.post("/customer/{phone}/quote/{quote_id}/order/create")
async def create_order_from_quote(phone: str, quote_id: str, key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers, customer = _get_customer_or_404(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)
    q = _find_quote(customer, quote_id)
    if not q:
        return HTMLResponse(content="Quote not found", status_code=404)
    q = _quote_total(q)
    existing = [o for o in customer.get("orders", []) if o.get("quote_id") == quote_id]
    if existing:
        return RedirectResponse(url=f"/customer/{phone}/order/{existing[0].get('order_id')}?key={DASHBOARD_KEY}", status_code=303)
    order_id = _generate_order_id(customer)
    order = {
        "order_id": order_id,
        "quote_id": quote_id,
        "product_name": q.get("product_name"),
        "details": q.get("details"),
        "qty": q.get("qty"),
        "total_amount": q.get("total"),
        "order_status": "PENDING",
        "production_status": "PENDING",
        "payment_status": "UNPAID",
        "priority": "NORMAL",
        "due_date": "",
        "dispatch_details": "",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "payments": [],
    }
    customer.setdefault("orders", []).append(order)
    q["status"] = "ORDER_CREATED"
    q["order_id"] = order_id
    customer["lead_status"] = "ORDER_CREATED"
    customer["pipeline_stage"] = "ORDER_CONFIRMED"
    _save_customers(customers)
    return RedirectResponse(url=f"/customer/{phone}/order/{order_id}?key={DASHBOARD_KEY}", status_code=303)


@app.get("/customer/{phone}/orders", response_class=HTMLResponse)
async def customer_orders(phone: str, key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers, customer = _get_customer_or_404(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)
    def esc(value):
        if value is None: return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")
    rows = ""
    for o in customer.get("orders", [])[::-1]:
        _payment_summary(o)
        rows += f"<tr><td><a href='/customer/{esc(phone)}/order/{esc(o.get('order_id'))}?key={esc(DASHBOARD_KEY)}'>{esc(o.get('order_id'))}</a></td><td>{esc(o.get('product_name'))}</td><td>{esc(o.get('qty'))}</td><td>{_money(o.get('total_amount'))}</td><td>{esc(o.get('order_status'))}</td><td>{esc(o.get('payment_status'))}</td><td>{esc(o.get('created_at'))}</td></tr>"
    if not rows:
        rows = "<tr><td colspan='7' style='text-align:center;padding:24px;color:#777'>No orders yet.</td></tr>"
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Customer Orders</title><style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} a.btn{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none}} table{{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden}} th,td{{padding:12px;border-bottom:1px solid #eee;text-align:left}} th{{background:#111;color:white}}</style></head><body><h1>Customer Orders</h1><p><a class='btn' href='/customer/{esc(phone)}?key={esc(DASHBOARD_KEY)}'>Back Customer</a> <a class='btn' href='/orders?key={esc(DASHBOARD_KEY)}'>All Orders</a></p><table><thead><tr><th>Order</th><th>Product</th><th>Qty</th><th>Total</th><th>Status</th><th>Payment</th><th>Created</th></tr></thead><tbody>{rows}</tbody></table></body></html>
    """)


@app.get("/customer/{phone}/order/{order_id}", response_class=HTMLResponse)
async def view_order(phone: str, order_id: str, key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers, customer = _get_customer_or_404(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)
    order = _find_order(customer, order_id)
    if not order:
        return HTMLResponse(content="Order not found", status_code=404)
    pay = _payment_summary(order)
    def esc(value):
        if value is None: return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")
    status_options = ''.join(f"<option value='{s}' {'selected' if order.get('order_status')==s else ''}>{s}</option>" for s in ORDER_STATUSES)
    priority_options = ''.join(f"<option value='{p}' {'selected' if order.get('priority')==p else ''}>{p}</option>" for p in PRODUCTION_PRIORITIES)
    payment_rows = ''.join(f"<tr><td>{esc(p.get('date'))}</td><td>{_money(p.get('amount'))}</td><td>{esc(p.get('mode'))}</td><td>{esc(p.get('note'))}</td></tr>" for p in order.get('payments', [])) or "<tr><td colspan='4' style='color:#777'>No payments added.</td></tr>"
    invoice_btn = f"<a class='btn' href='/customer/{esc(phone)}/order/{esc(order_id)}/invoice?key={esc(DASHBOARD_KEY)}'>Print Invoice</a>" if order.get('invoice_no') else f"<form style='display:inline' method='post' action='/customer/{esc(phone)}/order/{esc(order_id)}/invoice/create?key={esc(DASHBOARD_KEY)}'><button>Create Invoice</button></form>"
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Order {esc(order_id)}</title><style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} .card{{background:white;border:1px solid #e5e5e5;border-radius:14px;padding:18px}} a.btn,button{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none;border:0;cursor:pointer}} input,select,textarea{{width:100%;padding:10px;border:1px solid #ddd;border-radius:10px;box-sizing:border-box}} table{{width:100%;border-collapse:collapse}} th,td{{padding:10px;border-bottom:1px solid #eee;text-align:left}} th{{background:#111;color:white}} @media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}</style></head><body>
    <h1>Order {esc(order_id)}</h1><p><a class='btn' href='/customer/{esc(phone)}?key={esc(DASHBOARD_KEY)}'>Customer</a> <a class='btn' href='/orders?key={esc(DASHBOARD_KEY)}'>Orders Dashboard</a> {invoice_btn}</p>
    <div class='grid'><div class='card'><h2>Order Details</h2><p><b>Product:</b> {esc(order.get('product_name'))}<br><b>Details:</b> {esc(order.get('details'))}<br><b>Qty:</b> {esc(order.get('qty'))}<br><b>Total:</b> {_money(order.get('total_amount'))}<br><b>Paid:</b> {_money(pay['paid'])}<br><b>Balance:</b> {_money(pay['balance'])}<br><b>Payment:</b> {esc(pay['status'])}</p>
    <form method='post' action='/customer/{esc(phone)}/order/{esc(order_id)}/update?key={esc(DASHBOARD_KEY)}'><label>Status</label><select name='order_status'>{status_options}</select><br><br><label>Priority</label><select name='priority'>{priority_options}</select><br><br><label>Due Date</label><input type='date' name='due_date' value='{esc(order.get('due_date'))}'><br><br><label>Dispatch Details</label><textarea name='dispatch_details'>{esc(order.get('dispatch_details'))}</textarea><br><br><button>Update Order</button></form></div>
    <div class='card'><h2>Add Payment</h2><form method='post' action='/customer/{esc(phone)}/order/{esc(order_id)}/payment/add?key={esc(DASHBOARD_KEY)}'><label>Amount</label><input type='number' step='0.01' name='amount' required><br><br><label>Mode</label><input name='mode' placeholder='Cash / UPI / Bank'><br><br><label>Note</label><textarea name='note'></textarea><br><br><button>Add Payment</button></form><h3>Payment History</h3><table><thead><tr><th>Date</th><th>Amount</th><th>Mode</th><th>Note</th></tr></thead><tbody>{payment_rows}</tbody></table></div></div>
    </body></html>
    """)


@app.post("/customer/{phone}/order/{order_id}/update")
async def update_order(phone: str, order_id: str, key: str = "", order_status: str = Form("PENDING"), priority: str = Form("NORMAL"), due_date: str = Form(""), dispatch_details: str = Form("")):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers, customer = _get_customer_or_404(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)
    order = _find_order(customer, order_id)
    if not order:
        return HTMLResponse(content="Order not found", status_code=404)
    order["order_status"] = order_status if order_status in ORDER_STATUSES else order.get("order_status", "PENDING")
    order["production_status"] = order["order_status"]
    order["priority"] = priority if priority in PRODUCTION_PRIORITIES else "NORMAL"
    order["due_date"] = due_date
    order["dispatch_details"] = dispatch_details
    order["updated_at"] = datetime.utcnow().isoformat() + "Z"
    if order["order_status"] == "DISPATCHED":
        customer["pipeline_stage"] = "DISPATCHED"
    elif order["order_status"] == "DELIVERED":
        customer["pipeline_stage"] = "CLOSED"
        customer["lead_status"] = "CLOSED"
    _payment_summary(order)
    _save_customers(customers)
    return RedirectResponse(url=f"/customer/{phone}/order/{order_id}?key={DASHBOARD_KEY}", status_code=303)


@app.post("/customer/{phone}/order/{order_id}/payment/add")
async def add_order_payment(phone: str, order_id: str, key: str = "", amount: str = Form("0"), mode: str = Form(""), note: str = Form("")):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers, customer = _get_customer_or_404(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)
    order = _find_order(customer, order_id)
    if not order:
        return HTMLResponse(content="Order not found", status_code=404)
    order.setdefault("payments", []).append({"amount": float(amount or 0), "mode": mode, "note": note, "date": datetime.utcnow().isoformat()+"Z"})
    _payment_summary(order)
    order["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _save_customers(customers)
    return RedirectResponse(url=f"/customer/{phone}/order/{order_id}?key={DASHBOARD_KEY}", status_code=303)


@app.post("/customer/{phone}/order/{order_id}/invoice/create")
async def create_invoice(phone: str, order_id: str, key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers, customer = _get_customer_or_404(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)
    order = _find_order(customer, order_id)
    if not order:
        return HTMLResponse(content="Order not found", status_code=404)
    if not order.get("invoice_no"):
        order["invoice_no"] = _generate_invoice_no(customer)
        order["invoice_date"] = datetime.utcnow().strftime("%Y-%m-%d")
        order["gst_percent"] = "0"
    _save_customers(customers)
    return RedirectResponse(url=f"/customer/{phone}/order/{order_id}/invoice?key={DASHBOARD_KEY}", status_code=303)


@app.get("/customer/{phone}/order/{order_id}/invoice", response_class=HTMLResponse)
async def view_invoice(phone: str, order_id: str, key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    customers, customer = _get_customer_or_404(phone)
    if not customer:
        return HTMLResponse(content="Customer not found", status_code=404)
    order = _find_order(customer, order_id)
    if not order:
        return HTMLResponse(content="Order not found", status_code=404)
    pay = _payment_summary(order)
    def esc(value):
        if value is None: return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Invoice {esc(order.get('invoice_no'))}</title><style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} .invoice{{background:white;max-width:850px;margin:auto;padding:30px;border-radius:14px}} .top{{display:flex;justify-content:space-between}} table{{width:100%;border-collapse:collapse;margin-top:22px}} th,td{{padding:12px;border-bottom:1px solid #eee;text-align:left}} th{{background:#111;color:white}} .total{{text-align:right;font-size:22px;font-weight:700}} button,a.btn{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none;border:0}} @media print{{.actions{{display:none}} body{{background:white}} .invoice{{box-shadow:none}}}}</style></head><body><div class='invoice'><div class='actions'><button onclick='window.print()'>Print / Save PDF</button> <a class='btn' href='/customer/{esc(phone)}/order/{esc(order_id)}?key={esc(DASHBOARD_KEY)}'>Back Order</a></div><div class='top'><div><h1>Rhinestone Heritage</h1><p>Invoice: <b>{esc(order.get('invoice_no'))}</b><br>Date: {esc(order.get('invoice_date'))}<br>Order: {esc(order_id)}</p></div><div><b>Bill To:</b><br>{esc(phone)}</div></div><table><thead><tr><th>Product</th><th>Details</th><th>Qty</th><th>Total</th></tr></thead><tbody><tr><td>{esc(order.get('product_name'))}</td><td>{esc(order.get('details'))}</td><td>{esc(order.get('qty'))}</td><td>{_money(order.get('total_amount'))}</td></tr></tbody></table><p class='total'>Grand Total: {_money(order.get('total_amount'))}</p><p><b>Paid:</b> {_money(pay['paid'])}<br><b>Balance Due:</b> {_money(pay['balance'])}<br><b>Payment Status:</b> {esc(pay['status'])}</p></div></body></html>
    """)


@app.get("/orders", response_class=HTMLResponse)
async def orders_dashboard(key: str = "", status: str = "all"):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    def esc(value):
        if value is None: return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")
    rows = []
    for c in _load_customers().values():
        for o in c.get("orders", []):
            _payment_summary(o)
            if status == "all" or o.get("order_status") == status or o.get("payment_status") == status:
                rows.append((c.get("phone_number"), o))
    rows.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
    body = ''.join(f"<tr><td><a href='/customer/{esc(phone)}/order/{esc(o.get('order_id'))}?key={esc(DASHBOARD_KEY)}'>{esc(o.get('order_id'))}</a></td><td><a href='/customer/{esc(phone)}?key={esc(DASHBOARD_KEY)}'>{esc(phone)}</a></td><td>{esc(o.get('product_name'))}</td><td>{esc(o.get('qty'))}</td><td>{_money(o.get('total_amount'))}</td><td>{esc(o.get('order_status'))}</td><td>{esc(o.get('payment_status'))}</td><td>{esc(o.get('priority'))}</td><td>{esc(o.get('due_date'))}</td></tr>" for phone,o in rows) or "<tr><td colspan='9' style='text-align:center;padding:24px;color:#777'>No orders found.</td></tr>"
    total_value = sum(_order_total(o) for _, o in rows)
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Orders Dashboard</title><style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} .top{{display:flex;justify-content:space-between;align-items:center}} a.btn{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none}} .cards{{display:flex;gap:12px;flex-wrap:wrap}} .card{{background:white;padding:16px;border-radius:14px;border:1px solid #e5e5e5}} table{{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden;margin-top:16px}} th,td{{padding:12px;border-bottom:1px solid #eee;text-align:left}} th{{background:#111;color:white}}</style></head><body><div class='top'><h1>Orders Dashboard</h1><p><a class='btn' href='/dashboard?key={esc(DASHBOARD_KEY)}'>CRM</a> <a class='btn' href='/production?key={esc(DASHBOARD_KEY)}'>Production</a></p></div><div class='cards'><div class='card'><b>Total Orders</b><br>{len(rows)}</div><div class='card'><b>Total Value</b><br>{_money(total_value)}</div></div><p><a href='/orders?key={esc(DASHBOARD_KEY)}&status=all'>All</a> | <a href='/orders?key={esc(DASHBOARD_KEY)}&status=PENDING'>Pending</a> | <a href='/orders?key={esc(DASHBOARD_KEY)}&status=IN_PRODUCTION'>In Production</a> | <a href='/orders?key={esc(DASHBOARD_KEY)}&status=READY'>Ready</a> | <a href='/orders?key={esc(DASHBOARD_KEY)}&status=DISPATCHED'>Dispatched</a> | <a href='/orders?key={esc(DASHBOARD_KEY)}&status=UNPAID'>Unpaid</a></p><table><thead><tr><th>Order</th><th>Customer</th><th>Product</th><th>Qty</th><th>Total</th><th>Status</th><th>Payment</th><th>Priority</th><th>Due</th></tr></thead><tbody>{body}</tbody></table></body></html>
    """)


@app.get("/production", response_class=HTMLResponse)
async def production_dashboard(key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    def esc(value):
        if value is None: return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")
    rows = []
    for c in _load_customers().values():
        for o in c.get("orders", []):
            if o.get("order_status") in ("PENDING", "IN_PRODUCTION", "READY"):
                rows.append((c.get("phone_number"), o))
    rows.sort(key=lambda x: (x[1].get("priority") != "URGENT", x[1].get("due_date", "")))
    body = ''.join(f"<tr><td><a href='/customer/{esc(phone)}/order/{esc(o.get('order_id'))}?key={esc(DASHBOARD_KEY)}'>{esc(o.get('order_id'))}</a></td><td>{esc(phone)}</td><td>{esc(o.get('product_name'))}</td><td>{esc(o.get('qty'))}</td><td>{esc(o.get('order_status'))}</td><td>{esc(o.get('priority'))}</td><td>{esc(o.get('due_date'))}</td></tr>" for phone,o in rows) or "<tr><td colspan='7' style='text-align:center;padding:24px;color:#777'>No active production jobs.</td></tr>"
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Production Dashboard</title><style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} a.btn{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none}} table{{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden;margin-top:16px}} th,td{{padding:12px;border-bottom:1px solid #eee;text-align:left}} th{{background:#111;color:white}}</style></head><body><h1>Production Dashboard</h1><p><a class='btn' href='/orders?key={esc(DASHBOARD_KEY)}'>Orders</a> <a class='btn' href='/dashboard?key={esc(DASHBOARD_KEY)}'>CRM</a></p><table><thead><tr><th>Order</th><th>Customer</th><th>Product</th><th>Qty</th><th>Status</th><th>Priority</th><th>Due Date</th></tr></thead><tbody>{body}</tbody></table></body></html>
    """)


# ── Inventory Module v3.1–v3.5 ──────────────────────────────────────────────
# v3.1 Stone Stock • v3.2 Material Stock • v3.3 Stock Ledger
# v3.4 Low Stock Alerts • v3.5 Inventory Dashboard + CSV Export

INVENTORY_FILE = os.getenv("INVENTORY_FILE", "data/inventory.json")
INVENTORY_CATEGORIES = ["Stone", "Hotfix Film", "Transfer Tape", "Packing", "Machine", "Other"]
STOCK_ACTIONS = ["IN", "OUT", "ADJUST"]


def _load_inventory() -> dict:
    if not os.path.exists(INVENTORY_FILE):
        return {"items": {}, "ledger": []}
    try:
        with open(INVENTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("items", {})
        data.setdefault("ledger", [])
        return data
    except Exception as exc:
        logger.error("Failed to load inventory: %s", exc)
        return {"items": {}, "ledger": []}


def _save_inventory(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(INVENTORY_FILE), exist_ok=True)
        with open(INVENTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.error("Failed to save inventory: %s", exc)


def _inventory_item_id(category: str, name: str, variant: str) -> str:
    raw = f"{category}-{name}-{variant}".lower().strip()
    safe = "".join(ch if ch.isalnum() else "-" for ch in raw)
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-") or f"item-{int(datetime.utcnow().timestamp())}"


def _stock_number(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _fmt_qty(value) -> str:
    n = _stock_number(value)
    if n.is_integer():
        return str(int(n))
    return f"{n:.2f}"


def _inventory_summary(data: dict) -> dict:
    items = list(data.get("items", {}).values())
    total_items = len(items)
    low_stock = [i for i in items if _stock_number(i.get("current_stock")) <= _stock_number(i.get("min_stock"))]
    stones = [i for i in items if i.get("category") == "Stone"]
    materials = [i for i in items if i.get("category") != "Stone"]
    return {
        "total_items": total_items,
        "low_stock_count": len(low_stock),
        "stone_items": len(stones),
        "material_items": len(materials),
        "ledger_count": len(data.get("ledger", [])),
    }


@app.get("/inventory", response_class=HTMLResponse)
async def inventory_dashboard(key: str = "", category: str = "all", low: str = "0", q: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)

    data = _load_inventory()
    summary = _inventory_summary(data)
    items = list(data.get("items", {}).values())
    query = (q or "").strip().lower()

    if category != "all":
        items = [i for i in items if i.get("category") == category]
    if low == "1":
        items = [i for i in items if _stock_number(i.get("current_stock")) <= _stock_number(i.get("min_stock"))]
    if query:
        items = [i for i in items if query in str(i.get("name", "")).lower() or query in str(i.get("variant", "")).lower() or query in str(i.get("supplier", "")).lower()]

    def esc(value):
        if value is None:
            return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")

    cat_options = "".join(f"<option value='{esc(c)}'>{esc(c)}</option>" for c in INVENTORY_CATEGORIES)
    filter_links = " ".join([f"<a class='btn light' href='/inventory?key={esc(DASHBOARD_KEY)}&category={esc(c)}'>{esc(c)}</a>" for c in INVENTORY_CATEGORIES])

    rows = ""
    for item in sorted(items, key=lambda x: (x.get("category", ""), x.get("name", ""))):
        is_low = _stock_number(item.get("current_stock")) <= _stock_number(item.get("min_stock"))
        rows += f"""
        <tr class='{"low" if is_low else ""}'>
            <td><a href='/inventory/item/{esc(item.get('item_id'))}?key={esc(DASHBOARD_KEY)}'><b>{esc(item.get('name'))}</b></a><br><span>{esc(item.get('variant'))}</span></td>
            <td>{esc(item.get('category'))}</td>
            <td>{_fmt_qty(item.get('current_stock'))} {esc(item.get('unit'))}</td>
            <td>{_fmt_qty(item.get('min_stock'))} {esc(item.get('unit'))}</td>
            <td>{esc(item.get('supplier'))}</td>
            <td>{esc(item.get('updated_at'))[:19]}</td>
        </tr>
        """
    if not rows:
        rows = "<tr><td colspan='6' style='text-align:center;color:#777;padding:24px'>No inventory items found.</td></tr>"

    recent = ""
    for entry in data.get("ledger", [])[-10:][::-1]:
        recent += f"<tr><td>{esc(entry.get('created_at'))[:19]}</td><td>{esc(entry.get('action'))}</td><td>{esc(entry.get('item_name'))}</td><td>{_fmt_qty(entry.get('qty'))}</td><td>{esc(entry.get('note'))}</td></tr>"
    if not recent:
        recent = "<tr><td colspan='5' style='text-align:center;color:#777;padding:18px'>No stock movement yet.</td></tr>"

    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Inventory Dashboard</title>
    <style>body{{font-family:Arial;background:#f7f7f7;padding:24px;color:#111}} .top{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}} .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}} .card{{background:white;border:1px solid #e5e5e5;border-radius:14px;padding:16px}} .value{{font-size:26px;font-weight:800;margin-top:6px}} a.btn,button{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none;border:0;cursor:pointer;display:inline-block;margin:3px}} .light{{background:white!important;color:#111!important;border:1px solid #ddd!important}} table{{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden;margin-top:14px}} th,td{{padding:12px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}} th{{background:#111;color:white}} tr.low td{{background:#fff7ed}} input,select{{padding:10px;border:1px solid #ddd;border-radius:10px}} .grid{{display:grid;grid-template-columns:360px 1fr;gap:16px}} @media(max-width:900px){{body{{padding:14px}} .grid{{grid-template-columns:1fr}} table{{display:block;overflow-x:auto}}}}</style></head><body>
    <div class='top'><h1>Inventory Dashboard</h1><p><a class='btn' href='/dashboard?key={esc(DASHBOARD_KEY)}'>CRM</a> <a class='btn' href='/orders?key={esc(DASHBOARD_KEY)}'>Orders</a> <a class='btn' href='/inventory/export?key={esc(DASHBOARD_KEY)}'>Export CSV</a></p></div>
    <div class='cards'><div class='card'>Total Items<div class='value'>{summary['total_items']}</div></div><div class='card'>Stone Items<div class='value'>{summary['stone_items']}</div></div><div class='card'>Material Items<div class='value'>{summary['material_items']}</div></div><div class='card'>Low Stock<div class='value'>{summary['low_stock_count']}</div></div><div class='card'>Ledger Entries<div class='value'>{summary['ledger_count']}</div></div></div>
    <div class='grid'><div class='card'><h2>Add / Update Item</h2><form method='post' action='/inventory/item/save?key={esc(DASHBOARD_KEY)}'><label>Category</label><br><select name='category'>{cat_options}</select><br><br><label>Name</label><br><input name='name' required placeholder='SS4 Crystal / Transfer Tape'><br><br><label>Variant / Size / Colour</label><br><input name='variant' placeholder='1.8mm Crystal / 12 inch'><br><br><label>Unit</label><br><input name='unit' value='pcs'><br><br><label>Opening Stock</label><br><input type='number' step='0.01' name='current_stock' value='0'><br><br><label>Minimum Stock Alert</label><br><input type='number' step='0.01' name='min_stock' value='0'><br><br><label>Supplier</label><br><input name='supplier'><br><br><button>Save Item</button></form></div>
    <div><form method='get' action='/inventory'><input type='hidden' name='key' value='{esc(DASHBOARD_KEY)}'><input name='q' value='{esc(q)}' placeholder='Search stock...'> <button>Search</button> <a class='btn light' href='/inventory?key={esc(DASHBOARD_KEY)}'>All</a> <a class='btn light' href='/inventory?key={esc(DASHBOARD_KEY)}&low=1'>Low Stock</a> {filter_links}</form><table><thead><tr><th>Item</th><th>Category</th><th>Stock</th><th>Minimum</th><th>Supplier</th><th>Updated</th></tr></thead><tbody>{rows}</tbody></table><h2>Recent Stock Movement</h2><table><thead><tr><th>Date</th><th>Action</th><th>Item</th><th>Qty</th><th>Note</th></tr></thead><tbody>{recent}</tbody></table></div></div>
    </body></html>
    """)


@app.post("/inventory/item/save")
async def save_inventory_item(key: str = "", category: str = Form("Other"), name: str = Form(""), variant: str = Form(""), unit: str = Form("pcs"), current_stock: str = Form("0"), min_stock: str = Form("0"), supplier: str = Form("")):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    data = _load_inventory()
    now = datetime.utcnow().isoformat() + "Z"
    category = category if category in INVENTORY_CATEGORIES else "Other"
    item_id = _inventory_item_id(category, name, variant)
    old = data["items"].get(item_id, {})
    item = {
        "item_id": item_id,
        "category": category,
        "name": name.strip(),
        "variant": variant.strip(),
        "unit": unit.strip() or "pcs",
        "current_stock": _stock_number(current_stock),
        "min_stock": _stock_number(min_stock),
        "supplier": supplier.strip(),
        "created_at": old.get("created_at") or now,
        "updated_at": now,
    }
    data["items"][item_id] = item
    if not old:
        data["ledger"].append({"created_at": now, "item_id": item_id, "item_name": item["name"], "action": "OPENING", "qty": item["current_stock"], "balance": item["current_stock"], "note": "Opening stock"})
    _save_inventory(data)
    return RedirectResponse(url=f"/inventory/item/{item_id}?key={DASHBOARD_KEY}", status_code=303)


@app.get("/inventory/item/{item_id}", response_class=HTMLResponse)
async def inventory_item_detail(item_id: str, key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    data = _load_inventory()
    item = data.get("items", {}).get(item_id)
    if not item:
        return HTMLResponse(content="Inventory item not found", status_code=404)

    def esc(value):
        if value is None:
            return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")

    action_options = "".join(f"<option value='{a}'>{a}</option>" for a in STOCK_ACTIONS)
    cat_options = "".join(f"<option value='{esc(c)}' {'selected' if item.get('category')==c else ''}>{esc(c)}</option>" for c in INVENTORY_CATEGORIES)
    history = [e for e in data.get("ledger", []) if e.get("item_id") == item_id]
    rows = "".join(f"<tr><td>{esc(e.get('created_at'))[:19]}</td><td>{esc(e.get('action'))}</td><td>{_fmt_qty(e.get('qty'))}</td><td>{_fmt_qty(e.get('balance'))}</td><td>{esc(e.get('note'))}</td></tr>" for e in history[::-1]) or "<tr><td colspan='5' style='color:#777;text-align:center;padding:18px'>No history yet.</td></tr>"
    low_badge = "<span style='background:#fed7aa;padding:6px 10px;border-radius:999px;font-weight:700'>LOW STOCK</span>" if _stock_number(item.get("current_stock")) <= _stock_number(item.get("min_stock")) else "<span style='background:#dcfce7;padding:6px 10px;border-radius:999px;font-weight:700'>OK</span>"

    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>{esc(item.get('name'))}</title><style>body{{font-family:Arial;background:#f7f7f7;padding:24px}} .grid{{display:grid;grid-template-columns:360px 1fr;gap:16px}} .card{{background:white;border:1px solid #e5e5e5;border-radius:14px;padding:18px}} a.btn,button{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none;border:0;cursor:pointer}} input,select,textarea{{width:100%;padding:10px;border:1px solid #ddd;border-radius:10px;box-sizing:border-box}} table{{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden}} th,td{{padding:12px;border-bottom:1px solid #eee;text-align:left}} th{{background:#111;color:white}} @media(max-width:850px){{.grid{{grid-template-columns:1fr}}}}</style></head><body>
    <p><a class='btn' href='/inventory?key={esc(DASHBOARD_KEY)}'>Back Inventory</a></p><h1>{esc(item.get('name'))}</h1><p>{esc(item.get('variant'))} • Current Stock: <b>{_fmt_qty(item.get('current_stock'))} {esc(item.get('unit'))}</b> {low_badge}</p>
    <div class='grid'><div class='card'><h2>Stock In / Out</h2><form method='post' action='/inventory/item/{esc(item_id)}/movement?key={esc(DASHBOARD_KEY)}'><label>Action</label><select name='action'>{action_options}</select><br><br><label>Qty</label><input type='number' step='0.01' name='qty' required><br><br><label>Note</label><textarea name='note'></textarea><br><br><button>Save Movement</button></form><hr><h2>Edit Item</h2><form method='post' action='/inventory/item/save?key={esc(DASHBOARD_KEY)}'><label>Category</label><select name='category'>{cat_options}</select><br><br><label>Name</label><input name='name' value='{esc(item.get('name'))}' required><br><br><label>Variant</label><input name='variant' value='{esc(item.get('variant'))}'><br><br><label>Unit</label><input name='unit' value='{esc(item.get('unit'))}'><br><br><label>Current Stock</label><input type='number' step='0.01' name='current_stock' value='{esc(item.get('current_stock'))}'><br><br><label>Minimum Stock</label><input type='number' step='0.01' name='min_stock' value='{esc(item.get('min_stock'))}'><br><br><label>Supplier</label><input name='supplier' value='{esc(item.get('supplier'))}'><br><br><button>Update Item</button></form></div><div class='card'><h2>Stock History</h2><table><thead><tr><th>Date</th><th>Action</th><th>Qty</th><th>Balance</th><th>Note</th></tr></thead><tbody>{rows}</tbody></table></div></div>
    </body></html>
    """)


@app.post("/inventory/item/{item_id}/movement")
async def inventory_stock_movement(item_id: str, key: str = "", action: str = Form("IN"), qty: str = Form("0"), note: str = Form("")):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    data = _load_inventory()
    item = data.get("items", {}).get(item_id)
    if not item:
        return HTMLResponse(content="Inventory item not found", status_code=404)
    amount = _stock_number(qty)
    action = action if action in STOCK_ACTIONS else "IN"
    current = _stock_number(item.get("current_stock"))
    if action == "IN":
        current += amount
    elif action == "OUT":
        current -= amount
    else:
        current = amount
    item["current_stock"] = current
    item["updated_at"] = datetime.utcnow().isoformat() + "Z"
    data.setdefault("ledger", []).append({"created_at": item["updated_at"], "item_id": item_id, "item_name": item.get("name"), "action": action, "qty": amount, "balance": current, "note": note})
    _save_inventory(data)
    return RedirectResponse(url=f"/inventory/item/{item_id}?key={DASHBOARD_KEY}", status_code=303)


@app.get("/inventory/export")
async def export_inventory(key: str = ""):
    if key != DASHBOARD_KEY:
        return JSONResponse(content={"error": "Access denied"}, status_code=401)
    data = _load_inventory()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Item ID", "Category", "Name", "Variant", "Unit", "Current Stock", "Minimum Stock", "Supplier", "Updated At"])
    for i in sorted(data.get("items", {}).values(), key=lambda x: (x.get("category", ""), x.get("name", ""))):
        writer.writerow([i.get("item_id", ""), i.get("category", ""), i.get("name", ""), i.get("variant", ""), i.get("unit", ""), i.get("current_stock", ""), i.get("min_stock", ""), i.get("supplier", ""), i.get("updated_at", "")])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=rh_inventory.csv"})


@app.get("/inventory/ledger/export")
async def export_inventory_ledger(key: str = ""):
    if key != DASHBOARD_KEY:
        return JSONResponse(content={"error": "Access denied"}, status_code=401)
    data = _load_inventory()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Created At", "Item ID", "Item Name", "Action", "Qty", "Balance", "Note"])
    for e in data.get("ledger", []):
        writer.writerow([e.get("created_at", ""), e.get("item_id", ""), e.get("item_name", ""), e.get("action", ""), e.get("qty", ""), e.get("balance", ""), e.get("note", "")])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=rh_inventory_ledger.csv"})





# ── Operations + HR + Reports Module v3.6-v4.5 ───────────────────────────────
SUPPLIERS_FILE = os.getenv("SUPPLIERS_FILE", "data/suppliers.json")
PURCHASES_FILE = os.getenv("PURCHASES_FILE", "data/purchases.json")
EXPENSES_FILE = os.getenv("EXPENSES_FILE", "data/expenses.json")
STAFF_FILE = os.getenv("STAFF_FILE", "data/staff.json")
ATTENDANCE_FILE = os.getenv("ATTENDANCE_FILE", "data/attendance.json")
SALARY_FILE = os.getenv("SALARY_FILE", "data/salary.json")
CAMPAIGNS_FILE = os.getenv("CAMPAIGNS_FILE", "data/campaigns.json")
SETTINGS_FILE = os.getenv("SETTINGS_FILE", "data/settings.json")


def _json_load(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Failed to load %s: %s", path, exc)
        return default


def _json_save(path: str, data) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.error("Failed to save %s: %s", path, exc)


def _now_id(prefix: str) -> str:
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"


def _safe_html(value):
    if value is None:
        return ""
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")


def _money(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


@app.get("/ops", response_class=HTMLResponse)
async def operations_home(key: str = ""):
    if key != DASHBOARD_KEY:
        return HTMLResponse(content="Access Denied", status_code=401)
    suppliers = _json_load(SUPPLIERS_FILE, {})
    purchases = _json_load(PURCHASES_FILE, {})
    expenses = _json_load(EXPENSES_FILE, {})
    staff = _json_load(STAFF_FILE, {})
    attendance = _json_load(ATTENDANCE_FILE, [])
    campaigns = _json_load(CAMPAIGNS_FILE, {})
    po_open = sum(1 for p in purchases.values() if p.get("status") not in ("RECEIVED", "CANCELLED"))
    monthly_expense = sum(_money(e.get("amount")) for e in expenses.values() if str(e.get("date", ""))[:7] == datetime.utcnow().strftime("%Y-%m"))
    return HTMLResponse(content=f"""
    <!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>RH Ops</title><style>body{{font-family:Arial;background:#f7f7f7;padding:24px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}}.card{{background:#fff;border:1px solid #e5e5e5;border-radius:14px;padding:18px}}.v{{font-size:30px;font-weight:800}}a.btn{{display:inline-block;background:#111;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none;margin:4px}}</style></head><body>
    <h1>RH Operations Hub</h1><p><a class='btn' href='/dashboard?key={_safe_html(DASHBOARD_KEY)}'>CRM</a> <a class='btn' href='/inventory?key={_safe_html(DASHBOARD_KEY)}'>Inventory</a> <a class='btn' href='/reports?key={_safe_html(DASHBOARD_KEY)}'>Reports</a></p>
    <div class='cards'><div class='card'>Suppliers<div class='v'>{len(suppliers)}</div></div><div class='card'>Open Purchase Orders<div class='v'>{po_open}</div></div><div class='card'>This Month Expense<div class='v'>₹{monthly_expense:,.0f}</div></div><div class='card'>Staff<div class='v'>{len(staff)}</div></div><div class='card'>Attendance Records<div class='v'>{len(attendance)}</div></div><div class='card'>Campaigns<div class='v'>{len(campaigns)}</div></div></div>
    <p style='margin-top:20px'><a class='btn' href='/suppliers?key={_safe_html(DASHBOARD_KEY)}'>Suppliers</a><a class='btn' href='/purchase-orders?key={_safe_html(DASHBOARD_KEY)}'>Purchase Orders</a><a class='btn' href='/expenses?key={_safe_html(DASHBOARD_KEY)}'>Expenses</a><a class='btn' href='/staff?key={_safe_html(DASHBOARD_KEY)}'>Staff</a><a class='btn' href='/attendance?key={_safe_html(DASHBOARD_KEY)}'>Attendance</a><a class='btn' href='/salary?key={_safe_html(DASHBOARD_KEY)}'>Salary</a><a class='btn' href='/campaigns?key={_safe_html(DASHBOARD_KEY)}'>Campaigns</a><a class='btn' href='/settings?key={_safe_html(DASHBOARD_KEY)}'>Settings</a></p>
    </body></html>""")


@app.get("/suppliers", response_class=HTMLResponse)
async def suppliers_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(SUPPLIERS_FILE, {})
    rows = "".join(f"<tr><td>{_safe_html(s.get('name'))}</td><td>{_safe_html(s.get('phone'))}</td><td>{_safe_html(s.get('category'))}</td><td>{_safe_html(s.get('note'))}</td></tr>" for s in data.values()) or "<tr><td colspan='4'>No suppliers yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Suppliers v3.7</h1><p><a href='/ops?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/suppliers/save?key={_safe_html(DASHBOARD_KEY)}'><input name='name' placeholder='Supplier name' required> <input name='phone' placeholder='Phone'> <input name='category' placeholder='Category'> <input name='note' placeholder='Note'> <button>Save</button></form><br><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Name</th><th>Phone</th><th>Category</th><th>Note</th></tr>{rows}</table></body></html>""")


@app.post("/suppliers/save")
async def save_supplier(key: str = "", name: str = Form(""), phone: str = Form(""), category: str = Form(""), note: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(SUPPLIERS_FILE, {})
    sid = _now_id("SUP")
    data[sid] = {"supplier_id": sid, "name": name, "phone": phone, "category": category, "note": note, "created_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(SUPPLIERS_FILE, data)
    return RedirectResponse(url=f"/suppliers?key={DASHBOARD_KEY}", status_code=303)


@app.get("/purchase-orders", response_class=HTMLResponse)
async def purchase_orders_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(PURCHASES_FILE, {})
    rows = "".join(f"<tr><td>{_safe_html(p.get('po_id'))}</td><td>{_safe_html(p.get('supplier'))}</td><td>{_safe_html(p.get('item'))}</td><td>{_safe_html(p.get('qty'))}</td><td>₹{_money(p.get('amount')):,.0f}</td><td>{_safe_html(p.get('status'))}</td></tr>" for p in data.values()) or "<tr><td colspan='6'>No purchase orders yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Purchase Orders v3.6</h1><p><a href='/ops?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/purchase-orders/save?key={_safe_html(DASHBOARD_KEY)}'><input name='supplier' placeholder='Supplier'><input name='item' placeholder='Item'><input name='qty' placeholder='Qty'><input name='amount' placeholder='Amount'><select name='status'><option>ORDERED</option><option>PARTIAL</option><option>RECEIVED</option><option>CANCELLED</option></select><button>Save PO</button></form><br><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>PO ID</th><th>Supplier</th><th>Item</th><th>Qty</th><th>Amount</th><th>Status</th></tr>{rows}</table></body></html>""")


@app.post("/purchase-orders/save")
async def save_purchase_order(key: str = "", supplier: str = Form(""), item: str = Form(""), qty: str = Form(""), amount: str = Form(""), status: str = Form("ORDERED")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(PURCHASES_FILE, {})
    pid = _now_id("PO")
    data[pid] = {"po_id": pid, "supplier": supplier, "item": item, "qty": qty, "amount": _money(amount), "status": status, "created_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(PURCHASES_FILE, data)
    return RedirectResponse(url=f"/purchase-orders?key={DASHBOARD_KEY}", status_code=303)


@app.get("/expenses", response_class=HTMLResponse)
async def expenses_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(EXPENSES_FILE, {})
    total = sum(_money(e.get('amount')) for e in data.values())
    rows = "".join(f"<tr><td>{_safe_html(e.get('date'))}</td><td>{_safe_html(e.get('category'))}</td><td>₹{_money(e.get('amount')):,.0f}</td><td>{_safe_html(e.get('note'))}</td></tr>" for e in data.values()) or "<tr><td colspan='4'>No expenses yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Expense Tracker v3.8</h1><p><a href='/ops?key={_safe_html(DASHBOARD_KEY)}'>Back</a> | Total ₹{total:,.0f}</p><form method='post' action='/expenses/save?key={_safe_html(DASHBOARD_KEY)}'><input type='date' name='date'><input name='category' placeholder='Category'><input name='amount' placeholder='Amount'><input name='note' placeholder='Note'><button>Save Expense</button></form><br><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Date</th><th>Category</th><th>Amount</th><th>Note</th></tr>{rows}</table></body></html>""")


@app.post("/expenses/save")
async def save_expense(key: str = "", date: str = Form(""), category: str = Form(""), amount: str = Form(""), note: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(EXPENSES_FILE, {})
    eid = _now_id("EXP")
    data[eid] = {"expense_id": eid, "date": date or datetime.utcnow().strftime('%Y-%m-%d'), "category": category, "amount": _money(amount), "note": note, "created_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(EXPENSES_FILE, data)
    return RedirectResponse(url=f"/expenses?key={DASHBOARD_KEY}", status_code=303)


@app.get("/staff", response_class=HTMLResponse)
async def staff_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(STAFF_FILE, {})
    rows = "".join(f"<tr><td>{_safe_html(s.get('name'))}</td><td>{_safe_html(s.get('role'))}</td><td>₹{_money(s.get('monthly_salary')):,.0f}</td><td>{_safe_html(s.get('phone'))}</td></tr>" for s in data.values()) or "<tr><td colspan='4'>No staff yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Staff Management v3.9</h1><p><a href='/ops?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/staff/save?key={_safe_html(DASHBOARD_KEY)}'><input name='name' placeholder='Name'><input name='role' placeholder='Role'><input name='monthly_salary' placeholder='Monthly salary'><input name='phone' placeholder='Phone'><button>Save Staff</button></form><br><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Name</th><th>Role</th><th>Salary</th><th>Phone</th></tr>{rows}</table></body></html>""")


@app.post("/staff/save")
async def save_staff(key: str = "", name: str = Form(""), role: str = Form(""), monthly_salary: str = Form(""), phone: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(STAFF_FILE, {})
    sid = _now_id("STF")
    data[sid] = {"staff_id": sid, "name": name, "role": role, "monthly_salary": _money(monthly_salary), "phone": phone, "created_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(STAFF_FILE, data)
    return RedirectResponse(url=f"/staff?key={DASHBOARD_KEY}", status_code=303)


@app.get("/attendance", response_class=HTMLResponse)
async def attendance_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    staff = _json_load(STAFF_FILE, {})
    data = _json_load(ATTENDANCE_FILE, [])
    staff_opts = "".join(f"<option value='{_safe_html(s.get('name'))}'>{_safe_html(s.get('name'))}</option>" for s in staff.values())
    rows = "".join(f"<tr><td>{_safe_html(a.get('date'))}</td><td>{_safe_html(a.get('staff_name'))}</td><td>{_safe_html(a.get('status'))}</td><td>{_safe_html(a.get('note'))}</td></tr>" for a in data[::-1]) or "<tr><td colspan='4'>No attendance yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Attendance v4.0</h1><p><a href='/ops?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/attendance/save?key={_safe_html(DASHBOARD_KEY)}'><input type='date' name='date'><select name='staff_name'>{staff_opts}</select><select name='status'><option>PRESENT</option><option>ABSENT</option><option>HALF_DAY</option><option>LEAVE</option></select><input name='note' placeholder='Note'><button>Save Attendance</button></form><br><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Date</th><th>Staff</th><th>Status</th><th>Note</th></tr>{rows}</table></body></html>""")


@app.post("/attendance/save")
async def save_attendance(key: str = "", date: str = Form(""), staff_name: str = Form(""), status: str = Form("PRESENT"), note: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(ATTENDANCE_FILE, [])
    data.append({"date": date or datetime.utcnow().strftime('%Y-%m-%d'), "staff_name": staff_name, "status": status, "note": note, "created_at": datetime.utcnow().isoformat()+"Z"})
    _json_save(ATTENDANCE_FILE, data)
    return RedirectResponse(url=f"/attendance?key={DASHBOARD_KEY}", status_code=303)


@app.get("/salary", response_class=HTMLResponse)
async def salary_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    staff = _json_load(STAFF_FILE, {})
    records = _json_load(SALARY_FILE, {})
    staff_opts = "".join(f"<option value='{_safe_html(s.get('name'))}'>{_safe_html(s.get('name'))}</option>" for s in staff.values())
    rows = "".join(f"<tr><td>{_safe_html(r.get('month'))}</td><td>{_safe_html(r.get('staff_name'))}</td><td>₹{_money(r.get('salary')):,.0f}</td><td>₹{_money(r.get('advance')):,.0f}</td><td>₹{_money(r.get('net_payable')):,.0f}</td><td>{_safe_html(r.get('status'))}</td></tr>" for r in records.values()) or "<tr><td colspan='6'>No salary records.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Salary Module v4.1</h1><p><a href='/ops?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/salary/save?key={_safe_html(DASHBOARD_KEY)}'><input name='month' placeholder='2026-07'><select name='staff_name'>{staff_opts}</select><input name='salary' placeholder='Salary'><input name='advance' placeholder='Advance'><select name='status'><option>PENDING</option><option>PAID</option></select><button>Save Salary</button></form><br><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Month</th><th>Staff</th><th>Salary</th><th>Advance</th><th>Net</th><th>Status</th></tr>{rows}</table></body></html>""")


@app.post("/salary/save")
async def save_salary(key: str = "", month: str = Form(""), staff_name: str = Form(""), salary: str = Form(""), advance: str = Form("0"), status: str = Form("PENDING")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(SALARY_FILE, {})
    rid = _now_id("SAL")
    sal = _money(salary); adv = _money(advance)
    data[rid] = {"salary_id": rid, "month": month or datetime.utcnow().strftime('%Y-%m'), "staff_name": staff_name, "salary": sal, "advance": adv, "net_payable": sal - adv, "status": status, "created_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(SALARY_FILE, data)
    return RedirectResponse(url=f"/salary?key={DASHBOARD_KEY}", status_code=303)


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    customers = _load_customers()
    expenses = _json_load(EXPENSES_FILE, {})
    purchases = _json_load(PURCHASES_FILE, {})
    inventory = _json_load(INVENTORY_FILE, {"items": {}, "ledger": []}) if 'INVENTORY_FILE' in globals() else {"items": {}, "ledger": []}
    hot = sum(1 for c in customers.values() if c.get('is_hot_lead'))
    qualified = sum(1 for c in customers.values() if c.get('lead_status') == 'QUALIFIED_LEAD')
    exp_total = sum(_money(e.get('amount')) for e in expenses.values())
    po_total = sum(_money(p.get('amount')) for p in purchases.values())
    low_stock = sum(1 for i in inventory.get('items', {}).values() if _money(i.get('current_stock')) <= _money(i.get('min_stock')))
    return HTMLResponse(content=f"""<!doctype html><html><head><style>body{{font-family:Arial;background:#f7f7f7;padding:24px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}}.card{{background:white;border-radius:14px;padding:18px;border:1px solid #eee}}.v{{font-size:30px;font-weight:800}}</style></head><body><h1>Reports Dashboard v4.2</h1><p><a href='/ops?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><div class='cards'><div class='card'>Total Leads<div class='v'>{len(customers)}</div></div><div class='card'>Qualified Leads<div class='v'>{qualified}</div></div><div class='card'>Hot Leads<div class='v'>{hot}</div></div><div class='card'>Expense Total<div class='v'>₹{exp_total:,.0f}</div></div><div class='card'>Purchase Total<div class='v'>₹{po_total:,.0f}</div></div><div class='card'>Low Stock<div class='v'>{low_stock}</div></div></div><p><a href='/reports/export?key={_safe_html(DASHBOARD_KEY)}'>Download Summary CSV</a></p></body></html>""")


@app.get("/reports/export")
async def reports_export(key: str = ""):
    if key != DASHBOARD_KEY: return JSONResponse(content={"error": "Access denied"}, status_code=401)
    customers = _load_customers(); expenses = _json_load(EXPENSES_FILE, {}); purchases = _json_load(PURCHASES_FILE, {})
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Total Leads", len(customers)])
    writer.writerow(["Total Expenses", sum(_money(e.get('amount')) for e in expenses.values())])
    writer.writerow(["Total Purchase Orders Amount", sum(_money(p.get('amount')) for p in purchases.values())])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition":"attachment; filename=rh_reports_summary.csv"})


@app.get("/portal/approval/{phone}", response_class=HTMLResponse)
async def customer_approval_portal(phone: str):
    customers = _load_customers(); customer = customers.get(phone, {"phone_number": phone})
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><div style='max-width:650px;margin:auto;background:white;padding:24px;border-radius:16px'><h1>Rhinestone Heritage Approval Portal v4.3</h1><p>Customer: <b>{_safe_html(phone)}</b></p><p>Status: {_safe_html(customer.get('lead_status',''))}</p><p>This page is ready for future design approval, quote approval and order tracking links.</p><a href='https://wa.me/{_safe_html(phone)}'>Open WhatsApp</a></div></body></html>""")


@app.get("/campaigns", response_class=HTMLResponse)
async def campaigns_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(CAMPAIGNS_FILE, {})
    rows = "".join(f"<tr><td>{_safe_html(c.get('name'))}</td><td>{_safe_html(c.get('audience'))}</td><td>{_safe_html(c.get('status'))}</td><td>{_safe_html(c.get('message'))}</td></tr>" for c in data.values()) or "<tr><td colspan='4'>No campaigns yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Campaign Planner v4.4</h1><p><a href='/ops?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/campaigns/save?key={_safe_html(DASHBOARD_KEY)}'><input name='name' placeholder='Campaign name'><input name='audience' placeholder='Audience'><select name='status'><option>DRAFT</option><option>READY</option><option>SENT</option></select><input name='message' placeholder='Message'><button>Save Campaign</button></form><br><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Name</th><th>Audience</th><th>Status</th><th>Message</th></tr>{rows}</table></body></html>""")


@app.post("/campaigns/save")
async def save_campaign(key: str = "", name: str = Form(""), audience: str = Form(""), status: str = Form("DRAFT"), message: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(CAMPAIGNS_FILE, {})
    cid = _now_id("CMP")
    data[cid] = {"campaign_id": cid, "name": name, "audience": audience, "status": status, "message": message, "created_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(CAMPAIGNS_FILE, data)
    return RedirectResponse(url=f"/campaigns?key={DASHBOARD_KEY}", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(SETTINGS_FILE, {"business_name":"Rhinestone Heritage", "default_currency":"INR", "default_gst":"18"})
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Business Settings v4.5</h1><p><a href='/ops?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/settings/save?key={_safe_html(DASHBOARD_KEY)}'><label>Business Name</label><input name='business_name' value='{_safe_html(data.get('business_name'))}'><br><br><label>Currency</label><input name='default_currency' value='{_safe_html(data.get('default_currency'))}'><br><br><label>Default GST %</label><input name='default_gst' value='{_safe_html(data.get('default_gst'))}'><br><br><button>Save Settings</button></form></body></html>""")


@app.post("/settings/save")
async def save_settings(key: str = "", business_name: str = Form(""), default_currency: str = Form("INR"), default_gst: str = Form("18")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    _json_save(SETTINGS_FILE, {"business_name": business_name, "default_currency": default_currency, "default_gst": default_gst, "updated_at": datetime.utcnow().isoformat()+"Z"})
    return RedirectResponse(url=f"/settings?key={DASHBOARD_KEY}", status_code=303)


# ── v4.6 to v6.5 Enterprise Growth Pack ──────────────────────────────────────

def _audit(action: str, detail: dict | None = None) -> None:
    data = _json_load(AUDIT_FILE, [])
    data.append({"time": datetime.utcnow().isoformat()+"Z", "action": action, "detail": detail or {}})
    _json_save(AUDIT_FILE, data[-1000:])


@app.get("/growth", response_class=HTMLResponse)
async def growth_home(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    links = [
        ("Documents v4.6", "/documents"), ("Design Requests v4.7", "/design-requests"),
        ("Approvals v4.8", "/approvals"), ("Dispatch v4.9", "/dispatch"),
        ("Delivery Proof v5.0", "/delivery-proof"), ("Payment Reminders v5.1", "/payment-reminders"),
        ("Broadcast Queue v5.2", "/broadcast-queue"), ("Data Export v5.3", "/data-export"),
        ("Audit Log v5.4", "/audit"), ("System Status v6.5", "/system-status"),
    ]
    cards = "".join(f"<a class='card' href='{u}?key={_safe_html(DASHBOARD_KEY)}'>{t}</a>" for t,u in links)
    return HTMLResponse(content=f"""<!doctype html><html><head><style>body{{font-family:Arial;background:#f7f7f7;padding:24px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}}.card{{display:block;background:white;padding:20px;border-radius:14px;border:1px solid #eee;color:#111;text-decoration:none;font-weight:800}}</style></head><body><h1>RH Business OS Growth Pack v6.5</h1><p><a href='/dashboard?key={_safe_html(DASHBOARD_KEY)}'>Dashboard</a> · <a href='/ops?key={_safe_html(DASHBOARD_KEY)}'>Ops</a></p><div class='grid'>{cards}</div></body></html>""")


@app.get("/documents", response_class=HTMLResponse)
async def documents_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(DOCUMENTS_FILE, {})
    rows = "".join(f"<tr><td>{_safe_html(d.get('title'))}</td><td>{_safe_html(d.get('type'))}</td><td>{_safe_html(d.get('customer_phone'))}</td><td><a href='{_safe_html(d.get('url'))}' target='_blank'>Open</a></td><td>{_safe_html(d.get('note'))}</td></tr>" for d in data.values()) or "<tr><td colspan='5'>No documents.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Document Manager v4.6</h1><p><a href='/growth?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/documents/save?key={_safe_html(DASHBOARD_KEY)}'><input name='title' placeholder='Title'><input name='type' placeholder='Quote/Invoice/Design'><input name='customer_phone' placeholder='Customer phone'><input name='url' placeholder='File URL'><input name='note' placeholder='Note'><button>Save</button></form><br><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Title</th><th>Type</th><th>Customer</th><th>URL</th><th>Note</th></tr>{rows}</table></body></html>""")

@app.post("/documents/save")
async def save_document(key: str = "", title: str = Form(""), type: str = Form(""), customer_phone: str = Form(""), url: str = Form(""), note: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data=_json_load(DOCUMENTS_FILE, {}); did=_now_id("DOC")
    data[did]={"document_id":did,"title":title,"type":type,"customer_phone":customer_phone,"url":url,"note":note,"created_at":datetime.utcnow().isoformat()+"Z"}
    _json_save(DOCUMENTS_FILE,data); _audit("document_saved", {"document_id":did})
    return RedirectResponse(url=f"/documents?key={DASHBOARD_KEY}", status_code=303)


@app.get("/design-requests", response_class=HTMLResponse)
async def design_requests_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data=_json_load(DESIGN_REQUESTS_FILE,{})
    rows="".join(f"<tr><td>{_safe_html(r.get('request_id'))}</td><td>{_safe_html(r.get('customer_phone'))}</td><td>{_safe_html(r.get('design_type'))}</td><td>{_safe_html(r.get('size'))}</td><td>{_safe_html(r.get('stone_size'))}</td><td>{_safe_html(r.get('status'))}</td><td>{_safe_html(r.get('note'))}</td></tr>" for r in data.values()) or "<tr><td colspan='7'>No design requests.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Design Requests v4.7</h1><p><a href='/growth?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/design-requests/save?key={_safe_html(DASHBOARD_KEY)}'><input name='customer_phone' placeholder='Phone'><input name='design_type' placeholder='Tiger/Neck/Logo'><input name='size' placeholder='Size'><input name='stone_size' placeholder='SS4/SS6'><select name='status'><option>NEW</option><option>IN_DESIGN</option><option>PREVIEW_SENT</option><option>APPROVED</option></select><input name='note' placeholder='Note'><button>Save</button></form><br><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>ID</th><th>Phone</th><th>Type</th><th>Size</th><th>Stone</th><th>Status</th><th>Note</th></tr>{rows}</table></body></html>""")

@app.post("/design-requests/save")
async def save_design_request(key: str = "", customer_phone: str = Form(""), design_type: str = Form(""), size: str = Form(""), stone_size: str = Form(""), status: str = Form("NEW"), note: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data=_json_load(DESIGN_REQUESTS_FILE,{}); rid=_now_id("DR")
    data[rid]={"request_id":rid,"customer_phone":customer_phone,"design_type":design_type,"size":size,"stone_size":stone_size,"status":status,"note":note,"created_at":datetime.utcnow().isoformat()+"Z"}
    _json_save(DESIGN_REQUESTS_FILE,data); _audit("design_request_saved", {"request_id":rid})
    return RedirectResponse(url=f"/design-requests?key={DASHBOARD_KEY}", status_code=303)


@app.get("/approvals", response_class=HTMLResponse)
async def approvals_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data=_json_load(APPROVALS_FILE,{})
    rows="".join(f"<tr><td>{_safe_html(a.get('approval_id'))}</td><td>{_safe_html(a.get('customer_phone'))}</td><td>{_safe_html(a.get('item'))}</td><td>{_safe_html(a.get('status'))}</td><td>{_safe_html(a.get('approved_at'))}</td><td>{_safe_html(a.get('note'))}</td></tr>" for a in data.values()) or "<tr><td colspan='6'>No approvals.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Approval Tracker v4.8</h1><p><a href='/growth?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/approvals/save?key={_safe_html(DASHBOARD_KEY)}'><input name='customer_phone' placeholder='Phone'><input name='item' placeholder='Quote/Design/Order'><select name='status'><option>PENDING</option><option>APPROVED</option><option>CHANGES_NEEDED</option><option>REJECTED</option></select><input name='note' placeholder='Note'><button>Save Approval</button></form><br><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>ID</th><th>Phone</th><th>Item</th><th>Status</th><th>Approved At</th><th>Note</th></tr>{rows}</table></body></html>""")

@app.post("/approvals/save")
async def save_approval(key: str = "", customer_phone: str = Form(""), item: str = Form(""), status: str = Form("PENDING"), note: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data=_json_load(APPROVALS_FILE,{}); aid=_now_id("APR")
    data[aid]={"approval_id":aid,"customer_phone":customer_phone,"item":item,"status":status,"note":note,"approved_at":datetime.utcnow().isoformat()+"Z" if status=="APPROVED" else "","created_at":datetime.utcnow().isoformat()+"Z"}
    _json_save(APPROVALS_FILE,data); _audit("approval_saved", {"approval_id":aid,"status":status})
    return RedirectResponse(url=f"/approvals?key={DASHBOARD_KEY}", status_code=303)


@app.get("/dispatch", response_class=HTMLResponse)
async def dispatch_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data=_json_load(DISPATCH_FILE,{})
    rows="".join(f"<tr><td>{_safe_html(d.get('dispatch_id'))}</td><td>{_safe_html(d.get('order_id'))}</td><td>{_safe_html(d.get('courier'))}</td><td>{_safe_html(d.get('tracking_no'))}</td><td>{_safe_html(d.get('status'))}</td><td>{_safe_html(d.get('proof_url'))}</td></tr>" for d in data.values()) or "<tr><td colspan='6'>No dispatch records.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Dispatch Tracking v4.9</h1><p><a href='/growth?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/dispatch/save?key={_safe_html(DASHBOARD_KEY)}'><input name='order_id' placeholder='Order ID'><input name='courier' placeholder='Courier'><input name='tracking_no' placeholder='Tracking no'><select name='status'><option>PACKING</option><option>DISPATCHED</option><option>IN_TRANSIT</option><option>DELIVERED</option></select><input name='proof_url' placeholder='Proof URL'><button>Save Dispatch</button></form><br><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>ID</th><th>Order</th><th>Courier</th><th>Tracking</th><th>Status</th><th>Proof</th></tr>{rows}</table></body></html>""")

@app.post("/dispatch/save")
async def save_dispatch(key: str = "", order_id: str = Form(""), courier: str = Form(""), tracking_no: str = Form(""), status: str = Form("PACKING"), proof_url: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data=_json_load(DISPATCH_FILE,{}); did=_now_id("DSP")
    data[did]={"dispatch_id":did,"order_id":order_id,"courier":courier,"tracking_no":tracking_no,"status":status,"proof_url":proof_url,"updated_at":datetime.utcnow().isoformat()+"Z"}
    _json_save(DISPATCH_FILE,data); _audit("dispatch_saved", {"dispatch_id":did})
    return RedirectResponse(url=f"/dispatch?key={DASHBOARD_KEY}", status_code=303)


@app.get("/delivery-proof", response_class=HTMLResponse)
async def delivery_proof_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data=_json_load(DISPATCH_FILE,{})
    rows="".join(f"<tr><td>{_safe_html(d.get('order_id'))}</td><td>{_safe_html(d.get('status'))}</td><td>{_safe_html(d.get('proof_url'))}</td><td>{_safe_html(d.get('tracking_no'))}</td></tr>" for d in data.values() if d.get('proof_url') or d.get('status')=='DELIVERED') or "<tr><td colspan='4'>No delivery proof yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Delivery Proof v5.0</h1><p><a href='/growth?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Order</th><th>Status</th><th>Proof URL</th><th>Tracking</th></tr>{rows}</table></body></html>""")


@app.get("/payment-reminders", response_class=HTMLResponse)
async def payment_reminders_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data=_json_load(PAYMENT_REMINDERS_FILE,{})
    rows="".join(f"<tr><td>{_safe_html(p.get('customer_phone'))}</td><td>₹{_money(p.get('amount')):,.0f}</td><td>{_safe_html(p.get('due_date'))}</td><td>{_safe_html(p.get('status'))}</td><td>{_safe_html(p.get('note'))}</td></tr>" for p in data.values()) or "<tr><td colspan='5'>No payment reminders.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Payment Reminders v5.1</h1><p><a href='/growth?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/payment-reminders/save?key={_safe_html(DASHBOARD_KEY)}'><input name='customer_phone' placeholder='Phone'><input name='amount' placeholder='Amount'><input type='date' name='due_date'><select name='status'><option>PENDING</option><option>REMINDED</option><option>PAID</option></select><input name='note' placeholder='Note'><button>Save</button></form><br><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Phone</th><th>Amount</th><th>Due Date</th><th>Status</th><th>Note</th></tr>{rows}</table></body></html>""")

@app.post("/payment-reminders/save")
async def save_payment_reminder(key: str = "", customer_phone: str = Form(""), amount: str = Form(""), due_date: str = Form(""), status: str = Form("PENDING"), note: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data=_json_load(PAYMENT_REMINDERS_FILE,{}); pid=_now_id("PAYREM")
    data[pid]={"reminder_id":pid,"customer_phone":customer_phone,"amount":_money(amount),"due_date":due_date,"status":status,"note":note,"created_at":datetime.utcnow().isoformat()+"Z"}
    _json_save(PAYMENT_REMINDERS_FILE,data); _audit("payment_reminder_saved", {"reminder_id":pid})
    return RedirectResponse(url=f"/payment-reminders?key={DASHBOARD_KEY}", status_code=303)


@app.get("/broadcast-queue", response_class=HTMLResponse)
async def broadcast_queue_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data=_json_load(BROADCAST_QUEUE_FILE,{})
    rows="".join(f"<tr><td>{_safe_html(b.get('audience'))}</td><td>{_safe_html(b.get('status'))}</td><td>{_safe_html(b.get('scheduled_date'))}</td><td>{_safe_html(b.get('message'))}</td></tr>" for b in data.values()) or "<tr><td colspan='4'>No broadcast drafts.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Broadcast Queue v5.2</h1><p><b>Safe mode:</b> This only saves broadcast drafts. It does not auto-send bulk WhatsApp messages.</p><p><a href='/growth?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/broadcast-queue/save?key={_safe_html(DASHBOARD_KEY)}'><input name='audience' placeholder='Wholesalers / Retailers'><input type='date' name='scheduled_date'><select name='status'><option>DRAFT</option><option>READY</option><option>SENT_MANUALLY</option></select><input name='message' placeholder='Message'><button>Save Draft</button></form><br><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Audience</th><th>Status</th><th>Date</th><th>Message</th></tr>{rows}</table></body></html>""")

@app.post("/broadcast-queue/save")
async def save_broadcast_queue(key: str = "", audience: str = Form(""), scheduled_date: str = Form(""), status: str = Form("DRAFT"), message: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data=_json_load(BROADCAST_QUEUE_FILE,{}); bid=_now_id("BRC")
    data[bid]={"broadcast_id":bid,"audience":audience,"scheduled_date":scheduled_date,"status":status,"message":message,"created_at":datetime.utcnow().isoformat()+"Z"}
    _json_save(BROADCAST_QUEUE_FILE,data); _audit("broadcast_draft_saved", {"broadcast_id":bid})
    return RedirectResponse(url=f"/broadcast-queue?key={DASHBOARD_KEY}", status_code=303)


@app.get("/data-export")
async def data_export(key: str = ""):
    if key != DASHBOARD_KEY: return JSONResponse(content={"error":"Access denied"}, status_code=401)
    bundle = {
        "exported_at": datetime.utcnow().isoformat()+"Z", "version": "8.5.0",
        "customers": _load_customers(), "documents": _json_load(DOCUMENTS_FILE, {}),
        "design_requests": _json_load(DESIGN_REQUESTS_FILE, {}), "approvals": _json_load(APPROVALS_FILE, {}),
        "dispatch": _json_load(DISPATCH_FILE, {}), "payment_reminders": _json_load(PAYMENT_REMINDERS_FILE, {}),
        "broadcast_queue": _json_load(BROADCAST_QUEUE_FILE, {}),
    }
    return JSONResponse(content=bundle)


@app.get("/audit", response_class=HTMLResponse)
async def audit_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data=_json_load(AUDIT_FILE, [])[-300:]
    rows="".join(f"<tr><td>{_safe_html(a.get('time'))}</td><td>{_safe_html(a.get('action'))}</td><td>{_safe_html(a.get('detail'))}</td></tr>" for a in data[::-1]) or "<tr><td colspan='3'>No audit yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Audit Log v5.4</h1><p><a href='/growth?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Time</th><th>Action</th><th>Detail</th></tr>{rows}</table></body></html>""")


@app.get("/system-status", response_class=HTMLResponse)
async def system_status_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    checks = [("Messages", MESSAGES_FILE), ("Sessions", SESSIONS_FILE), ("Customers", CUSTOMERS_FILE), ("Documents", DOCUMENTS_FILE), ("Design Requests", DESIGN_REQUESTS_FILE), ("Approvals", APPROVALS_FILE), ("Dispatch", DISPATCH_FILE), ("Audit", AUDIT_FILE)]
    rows=""
    for name,path in checks:
        exists=os.path.exists(path); size=os.path.getsize(path) if exists else 0
        rows += f"<tr><td>{_safe_html(name)}</td><td>{_safe_html(path)}</td><td>{'OK' if exists else 'NEW'}</td><td>{size}</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>System Status v6.5</h1><p><a href='/growth?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Module</th><th>File</th><th>Status</th><th>Size Bytes</th></tr>{rows}</table></body></html>""")




# ── Phase 6: AI & Automation Pack v5.6-v6.5 ───────────────────────────────────
# Safe AI layer: rule-based suggestions first, no paid API required.
AI_SETTINGS_FILE = os.getenv("AI_SETTINGS_FILE", "data/ai_settings.json")
AI_SUGGESTIONS_FILE = os.getenv("AI_SUGGESTIONS_FILE", "data/ai_suggestions.json")
LEAD_SCORES_FILE = os.getenv("LEAD_SCORES_FILE", "data/lead_scores.json")
AUTOMATIONS_FILE = os.getenv("AUTOMATIONS_FILE", "data/automations.json")
SMART_REMINDERS_FILE = os.getenv("SMART_REMINDERS_FILE", "data/smart_reminders.json")
AUTO_QUOTES_FILE = os.getenv("AUTO_QUOTES_FILE", "data/auto_quote_suggestions.json")


def _ai_settings() -> dict:
    defaults = {
        "mode": "SAFE_RULE_BASED",
        "business_name": "Rhinestone Heritage",
        "default_tone": "professional_friendly",
        "auto_send_enabled": False,
        "auto_followup_enabled": False,
        "lead_score_threshold_hot": 70,
        "lead_score_threshold_warm": 40,
    }
    data = _json_load(AI_SETTINGS_FILE, {})
    defaults.update(data if isinstance(data, dict) else {})
    return defaults


def _lead_score(customer: dict) -> tuple[int, list[str]]:
    score = 10
    reasons = []
    buyer = (customer.get("buyer_type") or "").lower()
    status = customer.get("lead_status") or ""
    msg = (customer.get("last_message") or "").lower()
    count = int(customer.get("message_count") or 0)

    if buyer == "wholesaler": score += 25; reasons.append("Wholesaler/manufacturer lead")
    if status in ("QUALIFIED_LEAD", "ORDER_POSSIBLE"): score += 25; reasons.append("Qualified/order possible status")
    if customer.get("is_hot_lead") is True: score += 20; reasons.append("Marked hot by team")
    if count >= 3: score += 10; reasons.append("Multiple messages")
    if any(w in msg for w in ["qty", "quantity", "moq", "pcs", "piece", "price", "rate", "sample", "order"]):
        score += 15; reasons.append("Buying intent words found")
    if customer.get("followup_at") and not customer.get("followup_done_at"):
        score += 5; reasons.append("Follow-up pending")
    score = max(0, min(100, score))
    if not reasons:
        reasons.append("New lead with limited information")
    return score, reasons


def _suggest_reply(customer: dict) -> str:
    buyer = (customer.get("buyer_type") or "unknown").lower()
    status = customer.get("lead_status") or ""
    last = customer.get("last_message") or ""
    if buyer == "wholesaler" and status in ("WAITING_DESIGN", "WAITING_MOQ"):
        return ("Hello 👋 Thank you for contacting Rhinestone Heritage. Please share the design reference image and approximate quantity/MOQ. "
                "Our team will suggest the best rhinestone transfer sticker options with pricing.")
    if status == "QUALIFIED_LEAD":
        return ("Thank you for sharing the details. We are checking your requirement and will share the best price/quotation shortly. 🙏")
    if "price" in last.lower() or "rate" in last.lower():
        return ("Sure. Please share design size, stone color, and quantity required. Based on that we will calculate the best rate for you.")
    if buyer in ("retailer", "personal"):
        return MSG_RETAIL_PERSONAL
    return ("Hello 👋 Thank you for reaching out to Rhinestone Heritage. Please share your requirement, design reference and quantity so our team can help you quickly.")


def _suggest_quote(customer: dict) -> dict:
    buyer = (customer.get("buyer_type") or "unknown").lower()
    msg = (customer.get("last_message") or "").lower()
    qty = 100
    for token in msg.replace(",", " ").split():
        if token.isdigit():
            n = int(token)
            if 10 <= n <= 100000:
                qty = n; break
    product = "Custom Rhinestone Transfer Sticker"
    if "shirt" in msg: product = "Rhinestone Shirt Transfer"
    if "abaya" in msg: product = "Rhinestone Abaya Transfer"
    if buyer == "wholesaler" and qty >= 500:
        rate = 85
    elif buyer == "wholesaler":
        rate = 120
    else:
        rate = 180
    return {"product_name": product, "suggested_qty": qty, "suggested_rate": rate, "estimated_total": qty * rate, "note": "Final price depends on design size, stone count and colors."}


def _automation_due_today(customer: dict) -> bool:
    today = datetime.utcnow().date().isoformat()
    value = str(customer.get("followup_at") or customer.get("followup_date") or "")
    return value.startswith(today)


@app.get("/ai", response_class=HTMLResponse)
async def ai_dashboard(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    customers = _load_customers()
    settings = _ai_settings()
    scored = []
    for c in customers.values():
        s, reasons = _lead_score(c); scored.append((s, reasons, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    hot = sum(1 for s,_,__ in scored if s >= int(settings.get('lead_score_threshold_hot',70)))
    warm = sum(1 for s,_,__ in scored if 40 <= s < int(settings.get('lead_score_threshold_hot',70)))
    due = sum(1 for _,__,c in scored if _automation_due_today(c))
    rows = "".join(f"<tr><td><a href='/customer/{_safe_html(c.get('phone_number'))}?key={_safe_html(DASHBOARD_KEY)}'>{_safe_html(c.get('phone_number'))}</a></td><td>{s}</td><td>{_safe_html(c.get('buyer_type'))}</td><td>{_safe_html(c.get('lead_status'))}</td><td>{_safe_html(', '.join(reasons))}</td><td><a href='/ai/customer/{_safe_html(c.get('phone_number'))}?key={_safe_html(DASHBOARD_KEY)}'>Open AI</a></td></tr>" for s,reasons,c in scored[:100]) or "<tr><td colspan='6'>No leads yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>AI Automation</title><style>body{{font-family:Arial;background:#f7f7f7;padding:24px}}a.btn{{background:#111;color:white;padding:10px 14px;border-radius:10px;text-decoration:none}}.cards{{display:flex;gap:12px;flex-wrap:wrap}}.card{{background:white;border:1px solid #e5e5e5;border-radius:14px;padding:16px}}table{{width:100%;border-collapse:collapse;background:white;margin-top:16px}}th,td{{padding:10px;border-bottom:1px solid #eee;text-align:left}}th{{background:#111;color:white}}</style></head><body><h1>Phase 6 — AI & Automation v6.5</h1><p><a class='btn' href='/dashboard?key={_safe_html(DASHBOARD_KEY)}'>CRM</a> <a class='btn' href='/ai/settings?key={_safe_html(DASHBOARD_KEY)}'>AI Settings</a> <a class='btn' href='/ai/automation?key={_safe_html(DASHBOARD_KEY)}'>Automation Queue</a></p><div class='cards'><div class='card'><b>AI Mode</b><br>{_safe_html(settings.get('mode'))}</div><div class='card'><b>Hot AI Leads</b><br>{hot}</div><div class='card'><b>Warm Leads</b><br>{warm}</div><div class='card'><b>Due Today</b><br>{due}</div><div class='card'><b>Auto Send</b><br>{'OFF' if not settings.get('auto_send_enabled') else 'ON'}</div></div><h2>Smart Lead Scores</h2><table><tr><th>Phone</th><th>Score</th><th>Buyer</th><th>Status</th><th>Reasons</th><th>Action</th></tr>{rows}</table></body></html>""")


@app.get("/ai/customer/{phone}", response_class=HTMLResponse)
async def ai_customer_page(phone: str, key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    customers = _load_customers(); c = customers.get(phone)
    if not c: return HTMLResponse(content="Customer not found", status_code=404)
    score, reasons = _lead_score(c); reply = _suggest_reply(c); quote = _suggest_quote(c)
    suggestions = _json_load(AI_SUGGESTIONS_FILE, {})
    sid = _now_id("AIS")
    suggestions[sid] = {"suggestion_id": sid, "phone": phone, "reply": reply, "score": score, "reasons": reasons, "created_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(AI_SUGGESTIONS_FILE, suggestions)
    quotes = _json_load(AUTO_QUOTES_FILE, {}); quotes[sid] = {"suggestion_id": sid, "phone": phone, **quote, "created_at": datetime.utcnow().isoformat()+"Z"}; _json_save(AUTO_QUOTES_FILE, quotes)
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>AI Sales Assistant</h1><p><a href='/ai?key={_safe_html(DASHBOARD_KEY)}'>Back to AI</a> | <a href='/customer/{_safe_html(phone)}?key={_safe_html(DASHBOARD_KEY)}'>Customer Profile</a></p><div style='background:white;padding:18px;border-radius:14px'><h2>{_safe_html(phone)}</h2><p><b>Lead Score:</b> {score}/100</p><p><b>Reasons:</b> {_safe_html(', '.join(reasons))}</p><h3>AI Reply Suggestion</h3><form method='post' action='/ai/customer/{_safe_html(phone)}/send?key={_safe_html(DASHBOARD_KEY)}'><textarea name='message' style='width:100%;min-height:150px'>{_safe_html(reply)}</textarea><br><br><button style='background:#111;color:white;padding:10px 14px;border:0;border-radius:10px'>Send This WhatsApp Reply</button></form><h3>Auto Quote Suggestion</h3><p><b>Product:</b> {_safe_html(quote['product_name'])}</p><p><b>Qty:</b> {quote['suggested_qty']} | <b>Rate:</b> ₹{quote['suggested_rate']} | <b>Total:</b> ₹{quote['estimated_total']}</p><p>{_safe_html(quote['note'])}</p><form method='post' action='/ai/customer/{_safe_html(phone)}/reminder?key={_safe_html(DASHBOARD_KEY)}'><h3>Smart Reminder</h3><input type='datetime-local' name='remind_at'><input name='note' placeholder='Reminder note' style='width:50%;padding:10px'><button>Save Reminder</button></form></div></body></html>""")


@app.post("/ai/customer/{phone}/send")
async def ai_send_customer_reply(phone: str, key: str = "", message: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    if not message.strip(): return HTMLResponse(content="Message empty", status_code=400)
    success = await whatsapp.send_text_message(to=phone, body=message.strip())
    customers = _load_customers()
    if phone in customers:
        customers[phone]["last_ai_reply_sent_at"] = datetime.utcnow().isoformat()+"Z"
        customers[phone]["last_ai_reply"] = message.strip()
        _save_customers(customers)
    _append_message({"message_id": _now_id("OUTAI"), "from": "RH_BUSINESS_OS", "to": phone, "timestamp": str(int(datetime.utcnow().timestamp())), "received_at": datetime.utcnow().isoformat()+"Z", "type": "outbound_ai_suggestion", "body": message.strip(), "raw": {"manual_ai_send": True, "success": success}})
    _audit("ai_reply_sent" if success else "ai_reply_failed", {"phone": phone})
    return RedirectResponse(url=f"/ai/customer/{phone}?key={DASHBOARD_KEY}", status_code=303)


@app.post("/ai/customer/{phone}/reminder")
async def ai_save_reminder(phone: str, key: str = "", remind_at: str = Form(""), note: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(SMART_REMINDERS_FILE, {}); rid = _now_id("REM")
    data[rid] = {"reminder_id": rid, "phone": phone, "remind_at": remind_at, "note": note, "status": "PENDING", "created_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(SMART_REMINDERS_FILE, data); _audit("smart_reminder_saved", {"phone": phone, "reminder_id": rid})
    return RedirectResponse(url=f"/ai/customer/{phone}?key={DASHBOARD_KEY}", status_code=303)


@app.get("/ai/automation", response_class=HTMLResponse)
async def ai_automation_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    customers = _load_customers(); reminders = _json_load(SMART_REMINDERS_FILE, {})
    rows = ""
    for c in customers.values():
        score, reasons = _lead_score(c)
        if score >= 40 or _automation_due_today(c):
            phone = c.get('phone_number')
            rows += f"<tr><td>{_safe_html(phone)}</td><td>{score}</td><td>{_safe_html(c.get('lead_status'))}</td><td>{_safe_html(_suggest_reply(c))}</td><td><a href='/ai/customer/{_safe_html(phone)}?key={_safe_html(DASHBOARD_KEY)}'>Review</a></td></tr>"
    rem_rows = "".join(f"<tr><td>{_safe_html(r.get('phone'))}</td><td>{_safe_html(r.get('remind_at'))}</td><td>{_safe_html(r.get('status'))}</td><td>{_safe_html(r.get('note'))}</td></tr>" for r in reminders.values()) or "<tr><td colspan='4'>No smart reminders.</td></tr>"
    if not rows: rows = "<tr><td colspan='5'>No automation suggestions right now.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>Automation Queue v6.5</h1><p><b>Safe mode:</b> Auto-send is OFF by default. Review each suggestion before sending.</p><p><a href='/ai?key={_safe_html(DASHBOARD_KEY)}'>Back to AI</a></p><h2>Suggested Follow-ups</h2><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Phone</th><th>Score</th><th>Status</th><th>Suggested Reply</th><th>Action</th></tr>{rows}</table><h2>Smart Reminders</h2><table border='1' cellpadding='8' style='border-collapse:collapse;background:white'><tr><th>Phone</th><th>Time</th><th>Status</th><th>Note</th></tr>{rem_rows}</table></body></html>""")


@app.get("/ai/settings", response_class=HTMLResponse)
async def ai_settings_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    s = _ai_settings()
    return HTMLResponse(content=f"""<!doctype html><html><body style='font-family:Arial;background:#f7f7f7;padding:24px'><h1>AI Settings v6.5</h1><p><a href='/ai?key={_safe_html(DASHBOARD_KEY)}'>Back</a></p><form method='post' action='/ai/settings/save?key={_safe_html(DASHBOARD_KEY)}' style='background:white;padding:18px;border-radius:14px;max-width:650px'><label>Mode</label><select name='mode'><option {'selected' if s.get('mode')=='SAFE_RULE_BASED' else ''}>SAFE_RULE_BASED</option><option {'selected' if s.get('mode')=='OPENAI_READY_DISABLED' else ''}>OPENAI_READY_DISABLED</option></select><br><br><label>Default Tone</label><input name='default_tone' value='{_safe_html(s.get('default_tone'))}' style='width:100%;padding:10px'><br><br><label>Hot Lead Score Threshold</label><input name='lead_score_threshold_hot' value='{_safe_html(s.get('lead_score_threshold_hot'))}'><br><br><label>Warm Lead Score Threshold</label><input name='lead_score_threshold_warm' value='{_safe_html(s.get('lead_score_threshold_warm'))}'><br><br><label><input type='checkbox' name='auto_send_enabled' value='true' {'checked' if s.get('auto_send_enabled') else ''}> Auto-send enabled (not recommended)</label><br><label><input type='checkbox' name='auto_followup_enabled' value='true' {'checked' if s.get('auto_followup_enabled') else ''}> Auto follow-up enabled</label><br><br><button style='background:#111;color:white;padding:10px 14px;border:0;border-radius:10px'>Save Settings</button></form></body></html>""")


@app.post("/ai/settings/save")
async def ai_settings_save(key: str = "", mode: str = Form("SAFE_RULE_BASED"), default_tone: str = Form("professional_friendly"), lead_score_threshold_hot: str = Form("70"), lead_score_threshold_warm: str = Form("40"), auto_send_enabled: str = Form(""), auto_followup_enabled: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = {"mode": mode, "default_tone": default_tone, "lead_score_threshold_hot": int(lead_score_threshold_hot or 70), "lead_score_threshold_warm": int(lead_score_threshold_warm or 40), "auto_send_enabled": auto_send_enabled == "true", "auto_followup_enabled": auto_followup_enabled == "true", "updated_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(AI_SETTINGS_FILE, data); _audit("ai_settings_saved", data)
    return RedirectResponse(url=f"/ai/settings?key={DASHBOARD_KEY}", status_code=303)


@app.get("/ai/export")
async def ai_export(key: str = ""):
    if key != DASHBOARD_KEY: return JSONResponse(content={"error":"Access denied"}, status_code=401)
    customers = _load_customers(); lead_scores = {}
    for phone,c in customers.items():
        score, reasons = _lead_score(c); lead_scores[phone] = {"score": score, "reasons": reasons}
    return JSONResponse(content={"exported_at": datetime.utcnow().isoformat()+"Z", "version": "8.5.0", "lead_scores": lead_scores, "ai_settings": _ai_settings(), "suggestions": _json_load(AI_SUGGESTIONS_FILE, {}), "smart_reminders": _json_load(SMART_REMINDERS_FILE, {}), "auto_quote_suggestions": _json_load(AUTO_QUOTES_FILE, {})})




# ── Phase 7 Enterprise Controls v7.5 ─────────────────────────────────────────
# This layer keeps the existing dashboard key system safe, while preparing the
# app for proper multi-user login later. It does not break older CRM pages.
ENTERPRISE_USERS_FILE = os.getenv("ENTERPRISE_USERS_FILE", "data/enterprise_users.json")
ENTERPRISE_ROLES_FILE = os.getenv("ENTERPRISE_ROLES_FILE", "data/enterprise_roles.json")
ENTERPRISE_API_KEYS_FILE = os.getenv("ENTERPRISE_API_KEYS_FILE", "data/enterprise_api_keys.json")
ENTERPRISE_EMAIL_FILE = os.getenv("ENTERPRISE_EMAIL_FILE", "data/email_notifications.json")
ENTERPRISE_BACKUP_SCHEDULE_FILE = os.getenv("ENTERPRISE_BACKUP_SCHEDULE_FILE", "data/backup_schedule.json")
ENTERPRISE_SETTINGS_FILE = os.getenv("ENTERPRISE_SETTINGS_FILE", "data/enterprise_settings.json")

DEFAULT_ROLES = {
    "Admin": ["all"],
    "Sales": ["dashboard", "customers", "followups", "quotes", "orders", "broadcast"],
    "Designer": ["customers", "design_requests", "approvals", "production"],
    "Production": ["orders", "production", "dispatch", "inventory"],
    "Accounts": ["quotes", "invoices", "payments", "expenses", "reports"],
    "Viewer": ["dashboard", "reports"],
}


def _enterprise_roles() -> dict:
    roles = _json_load(ENTERPRISE_ROLES_FILE, {})
    if not roles:
        roles = {name: {"role_name": name, "permissions": perms, "created_at": datetime.utcnow().isoformat()+"Z"} for name, perms in DEFAULT_ROLES.items()}
        _json_save(ENTERPRISE_ROLES_FILE, roles)
    return roles


def _enterprise_users() -> dict:
    users = _json_load(ENTERPRISE_USERS_FILE, {})
    if not users:
        uid = _now_id("USR")
        users[uid] = {
            "user_id": uid,
            "name": "Aquib",
            "email": "",
            "role": "Admin",
            "status": "ACTIVE",
            "created_at": datetime.utcnow().isoformat()+"Z",
        }
        _json_save(ENTERPRISE_USERS_FILE, users)
    return users


def _phase7_nav() -> str:
    k = _safe_html(DASHBOARD_KEY)
    return f"""
    <p class='nav'>
      <a href='/dashboard?key={k}'>CRM</a>
      <a href='/enterprise?key={k}'>Enterprise</a>
      <a href='/enterprise/users?key={k}'>Users</a>
      <a href='/enterprise/roles?key={k}'>Roles</a>
      <a href='/enterprise/backup-scheduler?key={k}'>Backup Scheduler</a>
      <a href='/enterprise/api-keys?key={k}'>API Keys</a>
      <a href='/enterprise/email?key={k}'>Email Alerts</a>
      <a href='/enterprise/broadcast-scheduler?key={k}'>Broadcast Scheduler</a>
      <a href='/enterprise/system?key={k}'>System</a>
    </p>"""


def _phase7_style() -> str:
    return """
    <style>
      body{font-family:Arial;background:#f7f7f7;margin:0;padding:24px;color:#111} h1{margin:0 0 8px}
      .nav{display:flex;gap:8px;flex-wrap:wrap}.nav a,.btn{background:#111;color:white;padding:9px 12px;border-radius:10px;text-decoration:none;display:inline-block;border:0}
      .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}.card{background:white;border:1px solid #e5e5e5;border-radius:14px;padding:16px;box-shadow:0 2px 8px rgba(0,0,0,.04)}
      table{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden}th,td{padding:11px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}th{background:#111;color:white}
      input,select,textarea{width:100%;padding:10px;border:1px solid #ddd;border-radius:10px;box-sizing:border-box}button{background:#111;color:white;border:0;border-radius:10px;padding:10px 14px;cursor:pointer}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.muted{color:#666}.pill{display:inline-block;padding:5px 9px;border-radius:999px;background:#eee;font-size:12px;font-weight:700}
      @media(max-width:800px){body{padding:14px}.grid{grid-template-columns:1fr}table{display:block;overflow-x:auto}.nav a{width:100%;box-sizing:border-box}}
    </style>"""


@app.get("/enterprise", response_class=HTMLResponse)
async def enterprise_dashboard(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    users = _enterprise_users(); roles = _enterprise_roles()
    api_keys = _json_load(ENTERPRISE_API_KEYS_FILE, {})
    email_rules = _json_load(ENTERPRISE_EMAIL_FILE, {})
    backup = _json_load(ENTERPRISE_BACKUP_SCHEDULE_FILE, {})
    broadcasts = _json_load(BROADCAST_QUEUE_FILE, {})
    active_users = sum(1 for u in users.values() if u.get('status') == 'ACTIVE')
    scheduled_broadcasts = sum(1 for b in broadcasts.values() if b.get('schedule_at'))
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Enterprise Phase 7</title>{_phase7_style()}</head><body>
    <h1>Phase 7 — Enterprise Controls v7.5</h1><div class='muted'>Multi-user foundation, roles, backup scheduler, API integrations, email alerts, broadcast scheduler and mobile polish.</div>{_phase7_nav()}
    <div class='cards'>
      <div class='card'><b>Active Users</b><h2>{active_users}</h2></div><div class='card'><b>Roles</b><h2>{len(roles)}</h2></div><div class='card'><b>API Keys</b><h2>{len(api_keys)}</h2></div><div class='card'><b>Email Rules</b><h2>{len(email_rules)}</h2></div><div class='card'><b>Backup</b><h2>{_safe_html(backup.get('frequency','Not set'))}</h2></div><div class='card'><b>Scheduled Broadcasts</b><h2>{scheduled_broadcasts}</h2></div>
    </div><div class='card'><h2>Important</h2><p>Dashboard key security is still active. Phase 7 adds enterprise records and permissions foundation. Full password login can be connected later without breaking current CRM links.</p></div></body></html>""")


@app.get("/enterprise/users", response_class=HTMLResponse)
async def enterprise_users_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    users = _enterprise_users(); roles = _enterprise_roles()
    rows = ''.join(f"<tr><td>{_safe_html(u.get('name'))}</td><td>{_safe_html(u.get('email'))}</td><td><span class='pill'>{_safe_html(u.get('role'))}</span></td><td>{_safe_html(u.get('status'))}</td><td>{_safe_html(u.get('created_at'))}</td><td><form method='post' action='/enterprise/users/{_safe_html(uid)}/toggle?key={_safe_html(DASHBOARD_KEY)}'><button>{'Deactivate' if u.get('status')=='ACTIVE' else 'Activate'}</button></form></td></tr>" for uid,u in users.items())
    role_opts = ''.join(f"<option>{_safe_html(r)}</option>" for r in roles.keys())
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase7_style()}</head><body><h1>Multi-user Login Foundation</h1>{_phase7_nav()}<div class='grid'><div class='card'><h2>Add User</h2><form method='post' action='/enterprise/users/add?key={_safe_html(DASHBOARD_KEY)}'><label>Name</label><input name='name' required><br><br><label>Email</label><input name='email'><br><br><label>Role</label><select name='role'>{role_opts}</select><br><br><button>Add User</button></form></div><div class='card'><h2>Login Note</h2><p>This version stores users/roles safely. Current access still uses <b>DASHBOARD_KEY</b>. Later we can add password login screen and sessions.</p></div></div><br><table><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Created</th><th>Action</th></tr>{rows}</table></body></html>""")


@app.post("/enterprise/users/add")
async def enterprise_user_add(key: str = "", name: str = Form(""), email: str = Form(""), role: str = Form("Viewer")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    users = _enterprise_users(); uid = _now_id("USR")
    users[uid] = {"user_id": uid, "name": name.strip() or "New User", "email": email.strip(), "role": role, "status": "ACTIVE", "created_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(ENTERPRISE_USERS_FILE, users); _audit("enterprise_user_added", users[uid])
    return RedirectResponse(url=f"/enterprise/users?key={DASHBOARD_KEY}", status_code=303)


@app.post("/enterprise/users/{user_id}/toggle")
async def enterprise_user_toggle(user_id: str, key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    users = _enterprise_users()
    if user_id in users:
        users[user_id]['status'] = 'INACTIVE' if users[user_id].get('status') == 'ACTIVE' else 'ACTIVE'
        users[user_id]['updated_at'] = datetime.utcnow().isoformat()+"Z"
        _json_save(ENTERPRISE_USERS_FILE, users); _audit("enterprise_user_toggle", {"user_id": user_id, "status": users[user_id]['status']})
    return RedirectResponse(url=f"/enterprise/users?key={DASHBOARD_KEY}", status_code=303)


@app.get("/enterprise/roles", response_class=HTMLResponse)
async def enterprise_roles_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    roles = _enterprise_roles()
    rows = ''.join(f"<tr><td><b>{_safe_html(r.get('role_name'))}</b></td><td>{_safe_html(', '.join(r.get('permissions', [])))}</td><td>{_safe_html(r.get('created_at'))}</td></tr>" for r in roles.values())
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase7_style()}</head><body><h1>Roles & Permissions</h1>{_phase7_nav()}<div class='card'><form method='post' action='/enterprise/roles/add?key={_safe_html(DASHBOARD_KEY)}'><label>Role Name</label><input name='role_name' placeholder='Example: Marketing'><br><br><label>Permissions comma separated</label><input name='permissions' placeholder='dashboard,customers,broadcast,reports'><br><br><button>Add / Update Role</button></form></div><br><table><tr><th>Role</th><th>Permissions</th><th>Created</th></tr>{rows}</table></body></html>""")


@app.post("/enterprise/roles/add")
async def enterprise_role_add(key: str = "", role_name: str = Form(""), permissions: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    roles = _enterprise_roles(); name = role_name.strip() or "Custom"
    roles[name] = {"role_name": name, "permissions": [p.strip() for p in permissions.split(',') if p.strip()], "created_at": datetime.utcnow().isoformat()+"Z", "updated_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(ENTERPRISE_ROLES_FILE, roles); _audit("enterprise_role_saved", roles[name])
    return RedirectResponse(url=f"/enterprise/roles?key={DASHBOARD_KEY}", status_code=303)


@app.get("/enterprise/backup-scheduler", response_class=HTMLResponse)
async def enterprise_backup_scheduler(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    s = _json_load(ENTERPRISE_BACKUP_SCHEDULE_FILE, {"frequency":"DAILY", "time":"23:00", "enabled": False, "keep_days": 30})
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase7_style()}</head><body><h1>Backup Scheduler</h1>{_phase7_nav()}<div class='card'><form method='post' action='/enterprise/backup-scheduler/save?key={_safe_html(DASHBOARD_KEY)}'><label>Frequency</label><select name='frequency'><option {'selected' if s.get('frequency')=='DAILY' else ''}>DAILY</option><option {'selected' if s.get('frequency')=='WEEKLY' else ''}>WEEKLY</option></select><br><br><label>Backup Time</label><input name='time' value='{_safe_html(s.get('time'))}'><br><br><label>Keep Days</label><input name='keep_days' value='{_safe_html(s.get('keep_days'))}'><br><br><label><input type='checkbox' name='enabled' value='true' {'checked' if s.get('enabled') else ''}> Enabled</label><br><br><button>Save Schedule</button></form></div><p class='muted'>Scheduler setting is saved. Actual automatic cron can be connected on hosting later.</p></body></html>""")


@app.post("/enterprise/backup-scheduler/save")
async def enterprise_backup_scheduler_save(key: str = "", frequency: str = Form("DAILY"), time: str = Form("23:00"), keep_days: str = Form("30"), enabled: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = {"frequency": frequency, "time": time, "keep_days": int(keep_days or 30), "enabled": enabled == 'true', "updated_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(ENTERPRISE_BACKUP_SCHEDULE_FILE, data); _audit("backup_schedule_saved", data)
    return RedirectResponse(url=f"/enterprise/backup-scheduler?key={DASHBOARD_KEY}", status_code=303)


@app.get("/enterprise/api-keys", response_class=HTMLResponse)
async def enterprise_api_keys(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    keys = _json_load(ENTERPRISE_API_KEYS_FILE, {})
    rows = ''.join(f"<tr><td>{_safe_html(k.get('name'))}</td><td>{_safe_html(k.get('prefix'))}••••••</td><td>{_safe_html(k.get('status'))}</td><td>{_safe_html(k.get('created_at'))}</td></tr>" for k in keys.values()) or "<tr><td colspan='4'>No API keys yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase7_style()}</head><body><h1>API Integrations</h1>{_phase7_nav()}<div class='card'><form method='post' action='/enterprise/api-keys/create?key={_safe_html(DASHBOARD_KEY)}'><label>Integration Name</label><input name='name' placeholder='Shopify / RH Studio AI / Website'><br><br><button>Create API Key Record</button></form></div><br><table><tr><th>Name</th><th>Key</th><th>Status</th><th>Created</th></tr>{rows}</table><p class='muted'>Keys are stored as masked records for safe planning. Connect real token verification later when external apps are ready.</p></body></html>""")


@app.post("/enterprise/api-keys/create")
async def enterprise_api_key_create(key: str = "", name: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    keys = _json_load(ENTERPRISE_API_KEYS_FILE, {}); kid = _now_id("API"); raw = _now_id("RHKEY")
    keys[kid] = {"key_id": kid, "name": name.strip() or "Integration", "prefix": raw[:12], "status": "ACTIVE", "created_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(ENTERPRISE_API_KEYS_FILE, keys); _audit("api_key_record_created", {"key_id": kid, "name": name})
    return RedirectResponse(url=f"/enterprise/api-keys?key={DASHBOARD_KEY}", status_code=303)


@app.get("/enterprise/email", response_class=HTMLResponse)
async def enterprise_email_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    rules = _json_load(ENTERPRISE_EMAIL_FILE, {})
    rows = ''.join(f"<tr><td>{_safe_html(r.get('event'))}</td><td>{_safe_html(r.get('to_email'))}</td><td>{_safe_html(r.get('status'))}</td><td>{_safe_html(r.get('created_at'))}</td></tr>" for r in rules.values()) or "<tr><td colspan='4'>No email rules.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase7_style()}</head><body><h1>Email Notifications</h1>{_phase7_nav()}<div class='card'><form method='post' action='/enterprise/email/add?key={_safe_html(DASHBOARD_KEY)}'><label>Event</label><select name='event'><option>NEW_LEAD</option><option>QUOTE_SENT</option><option>ORDER_CONFIRMED</option><option>PAYMENT_DUE</option><option>LOW_STOCK</option></select><br><br><label>Email To</label><input name='to_email' placeholder='team@example.com'><br><br><button>Add Rule</button></form></div><br><table><tr><th>Event</th><th>Email To</th><th>Status</th><th>Created</th></tr>{rows}</table></body></html>""")


@app.post("/enterprise/email/add")
async def enterprise_email_add(key: str = "", event: str = Form("NEW_LEAD"), to_email: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    rules = _json_load(ENTERPRISE_EMAIL_FILE, {}); rid = _now_id("EML")
    rules[rid] = {"rule_id": rid, "event": event, "to_email": to_email.strip(), "status": "ACTIVE", "created_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(ENTERPRISE_EMAIL_FILE, rules); _audit("email_rule_added", rules[rid])
    return RedirectResponse(url=f"/enterprise/email?key={DASHBOARD_KEY}", status_code=303)


@app.get("/enterprise/broadcast-scheduler", response_class=HTMLResponse)
async def enterprise_broadcast_scheduler(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    queue = _json_load(BROADCAST_QUEUE_FILE, {})
    rows = ''.join(f"<tr><td>{_safe_html(b.get('title'))}</td><td>{_safe_html(b.get('audience'))}</td><td>{_safe_html(b.get('schedule_at'))}</td><td>{_safe_html(b.get('status'))}</td><td>{_safe_html(b.get('message'))}</td></tr>" for b in sorted(queue.values(), key=lambda x: x.get('created_at',''), reverse=True)[:100]) or "<tr><td colspan='5'>No broadcasts.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase7_style()}</head><body><h1>WhatsApp Broadcast Scheduler</h1>{_phase7_nav()}<div class='card'><form method='post' action='/enterprise/broadcast-scheduler/add?key={_safe_html(DASHBOARD_KEY)}'><label>Title</label><input name='title'><br><br><label>Audience</label><select name='audience'><option>all</option><option>wholesaler</option><option>retailer</option><option>personal</option><option>hot</option></select><br><br><label>Schedule At</label><input type='datetime-local' name='schedule_at'><br><br><label>Message</label><textarea name='message' rows='5'></textarea><br><br><button>Save Broadcast</button></form></div><br><table><tr><th>Title</th><th>Audience</th><th>Schedule</th><th>Status</th><th>Message</th></tr>{rows}</table><p class='muted'>Safe mode: this only schedules queue records. Actual bulk send should be reviewed before sending to protect WhatsApp quality rating.</p></body></html>""")


@app.post("/enterprise/broadcast-scheduler/add")
async def enterprise_broadcast_add(key: str = "", title: str = Form(""), audience: str = Form("all"), schedule_at: str = Form(""), message: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    queue = _json_load(BROADCAST_QUEUE_FILE, {}); bid = _now_id("BCAST")
    queue[bid] = {"broadcast_id": bid, "title": title.strip() or "Broadcast", "audience": audience, "schedule_at": schedule_at, "message": message.strip(), "status": "SCHEDULED", "created_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(BROADCAST_QUEUE_FILE, queue); _audit("broadcast_scheduled", queue[bid])
    return RedirectResponse(url=f"/enterprise/broadcast-scheduler?key={DASHBOARD_KEY}", status_code=303)


@app.get("/enterprise/system", response_class=HTMLResponse)
async def enterprise_system_page(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    files = [CUSTOMERS_FILE, MESSAGES_FILE, SESSIONS_FILE, DOCUMENTS_FILE, DESIGN_REQUESTS_FILE, APPROVALS_FILE, DISPATCH_FILE, BROADCAST_QUEUE_FILE, AUDIT_FILE, ENTERPRISE_USERS_FILE, ENTERPRISE_ROLES_FILE]
    rows = ''
    for path in files:
        exists = os.path.exists(path); size = os.path.getsize(path) if exists else 0
        rows += f"<tr><td>{_safe_html(path)}</td><td>{'OK' if exists else 'Missing'}</td><td>{size} bytes</td></tr>"
    audit_count = len(_json_load(AUDIT_FILE, [])) if isinstance(_json_load(AUDIT_FILE, []), list) else len(_json_load(AUDIT_FILE, {}))
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase7_style()}</head><body><h1>System Status & Security</h1>{_phase7_nav()}<div class='cards'><div class='card'><b>App Version</b><h2>8.5.0</h2></div><div class='card'><b>Audit Events</b><h2>{audit_count}</h2></div><div class='card'><b>Mobile UI</b><h2>Improved</h2></div></div><table><tr><th>Data File</th><th>Status</th><th>Size</th></tr>{rows}</table></body></html>""")


@app.get("/enterprise/export")
async def enterprise_export(key: str = ""):
    if key != DASHBOARD_KEY: return JSONResponse(content={"error":"Access denied"}, status_code=401)
    return JSONResponse(content={"exported_at": datetime.utcnow().isoformat()+"Z", "version":"8.5.0", "users": _enterprise_users(), "roles": _enterprise_roles(), "api_keys": _json_load(ENTERPRISE_API_KEYS_FILE, {}), "email_notifications": _json_load(ENTERPRISE_EMAIL_FILE, {}), "backup_schedule": _json_load(ENTERPRISE_BACKUP_SCHEDULE_FILE, {}), "broadcast_queue": _json_load(BROADCAST_QUEUE_FILE, {})})




# ── Phase 9 — Integration & Launch Readiness Pack v9.5 ───────────────────────
PHASE9_INTEGRATIONS_FILE = os.getenv("PHASE9_INTEGRATIONS_FILE", "data/phase9_integrations.json")
PHASE9_WEBHOOK_LOG_FILE = os.getenv("PHASE9_WEBHOOK_LOG_FILE", "data/phase9_webhook_log.json")
PHASE9_PORTAL_SETTINGS_FILE = os.getenv("PHASE9_PORTAL_SETTINGS_FILE", "data/phase9_portal_settings.json")
PHASE9_LAUNCH_CHECKLIST_FILE = os.getenv("PHASE9_LAUNCH_CHECKLIST_FILE", "data/phase9_launch_checklist.json")


# Compatibility alias for Phase 8/9/10 pages
_phase8_style = _phase7_style

def _phase9_nav():
    k = _safe_html(DASHBOARD_KEY)
    return f"""
    <div class='nav'>
      <a class='btn' href='/phase9/dashboard?key={k}'>Phase 9 Home</a>
      <a class='btn light' href='/phase9/integrations?key={k}'>Integrations</a>
      <a class='btn light' href='/phase9/webhooks?key={k}'>Webhook Logs</a>
      <a class='btn light' href='/phase9/portal?key={k}'>Customer Portal</a>
      <a class='btn light' href='/phase9/performance?key={k}'>Performance</a>
      <a class='btn light' href='/phase9/launch?key={k}'>Launch Checklist</a>
      <a class='btn light' href='/dashboard?key={k}'>CRM</a>
    </div><br>
    """


def _phase9_default_integrations():
    return {
        "shopify": {"name": "Shopify Store", "status": "planned", "owner": "Aquib", "notes": "Sync products, orders and customers later."},
        "rh_studio_ai": {"name": "RH Studio AI", "status": "planned", "owner": "Design Team", "notes": "Connect design processing after Studio AI is stable."},
        "gmail": {"name": "Gmail / Email", "status": "planned", "owner": "Sales Team", "notes": "Send quotation and invoice copies by email."},
        "google_drive": {"name": "Google Drive", "status": "planned", "owner": "Office", "notes": "Store quote PDFs, invoices and design files."},
        "meta_ads": {"name": "Meta Ads Leads", "status": "planned", "owner": "Marketing", "notes": "Import Instagram/Facebook lead forms."},
    }


@app.get("/phase9/dashboard", response_class=HTMLResponse)
async def phase9_dashboard(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    integrations = _json_load(PHASE9_INTEGRATIONS_FILE, _phase9_default_integrations())
    logs = _json_load(PHASE9_WEBHOOK_LOG_FILE, [])
    portal = _json_load(PHASE9_PORTAL_SETTINGS_FILE, {"enabled": "no", "portal_name": "RH Customer Portal", "public_upload": "no"})
    active = sum(1 for v in integrations.values() if v.get("status") == "active")
    planned = sum(1 for v in integrations.values() if v.get("status") == "planned")
    rows = ''.join(f"<tr><td>{_safe_html(v.get('name'))}</td><td><span class='badge'>{_safe_html(v.get('status'))}</span></td><td>{_safe_html(v.get('owner'))}</td></tr>" for v in integrations.values())
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase8_style()}</head><body><h1>Phase 9 — Integration & Launch Readiness</h1>{_phase9_nav()}<div class='cards'><div class='card'><div class='muted'>Integrations</div><div class='kpi'>{len(integrations)}</div></div><div class='card'><div class='muted'>Active</div><div class='kpi good'>{active}</div></div><div class='card'><div class='muted'>Planned</div><div class='kpi warn'>{planned}</div></div><div class='card'><div class='muted'>Webhook Test Logs</div><div class='kpi'>{len(logs)}</div></div></div><div class='grid'><div class='card'><h2>Integration Map</h2><table><tr><th>Name</th><th>Status</th><th>Owner</th></tr>{rows}</table></div><div class='card'><h2>Portal Status</h2><p><b>Name:</b> {_safe_html(portal.get('portal_name'))}</p><p><b>Enabled:</b> {_safe_html(portal.get('enabled'))}</p><p><b>Public Upload:</b> {_safe_html(portal.get('public_upload'))}</p><p class='muted'>Phase 9 prepares all external connections safely. Real API secrets should stay in .env only.</p></div></div></body></html>""")


@app.get("/phase9/integrations", response_class=HTMLResponse)
async def phase9_integrations(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(PHASE9_INTEGRATIONS_FILE, _phase9_default_integrations())
    rows = ''.join(f"""<tr><td><b>{_safe_html(v.get('name'))}</b><br><span class='muted'>{_safe_html(k)}</span></td><td>{_safe_html(v.get('status'))}</td><td>{_safe_html(v.get('owner'))}</td><td>{_safe_html(v.get('notes'))}</td><td><form method='post' action='/phase9/integrations/update?key={_safe_html(DASHBOARD_KEY)}'><input type='hidden' name='integration_id' value='{_safe_html(k)}'><select name='status'><option value='planned'>planned</option><option value='active'>active</option><option value='paused'>paused</option><option value='blocked'>blocked</option></select><input name='owner' value='{_safe_html(v.get('owner'))}'><input name='notes' value='{_safe_html(v.get('notes'))}'><button>Save</button></form></td></tr>""" for k,v in data.items())
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase8_style()}</head><body><h1>Integration Center</h1>{_phase9_nav()}<table><tr><th>Integration</th><th>Status</th><th>Owner</th><th>Notes</th><th>Update</th></tr>{rows}</table><br><div class='card'><h2>Add Custom Integration</h2><form method='post' action='/phase9/integrations/add?key={_safe_html(DASHBOARD_KEY)}'><input name='integration_id' placeholder='unique_id'><br><br><input name='name' placeholder='Integration name'><br><br><input name='owner' placeholder='Owner'><br><br><textarea name='notes' placeholder='Notes'></textarea><br><br><button>Add Integration</button></form></div></body></html>""")


@app.post("/phase9/integrations/add")
async def phase9_integrations_add(key: str = "", integration_id: str = Form(""), name: str = Form(""), owner: str = Form(""), notes: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(PHASE9_INTEGRATIONS_FILE, _phase9_default_integrations())
    iid = (integration_id or name or "custom").strip().lower().replace(" ", "_")
    data[iid] = {"name": name or iid, "status": "planned", "owner": owner, "notes": notes, "created_at": datetime.utcnow().isoformat()+"Z"}
    _json_save(PHASE9_INTEGRATIONS_FILE, data); _audit("phase9_integration_added", {"integration_id": iid})
    return RedirectResponse(url=f"/phase9/integrations?key={DASHBOARD_KEY}", status_code=303)


@app.post("/phase9/integrations/update")
async def phase9_integrations_update(key: str = "", integration_id: str = Form(""), status: str = Form("planned"), owner: str = Form(""), notes: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(PHASE9_INTEGRATIONS_FILE, _phase9_default_integrations())
    if integration_id in data:
        data[integration_id].update({"status": status, "owner": owner, "notes": notes, "updated_at": datetime.utcnow().isoformat()+"Z"})
    _json_save(PHASE9_INTEGRATIONS_FILE, data); _audit("phase9_integration_updated", {"integration_id": integration_id, "status": status})
    return RedirectResponse(url=f"/phase9/integrations?key={DASHBOARD_KEY}", status_code=303)


@app.get("/phase9/webhooks", response_class=HTMLResponse)
async def phase9_webhooks(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    logs = _json_load(PHASE9_WEBHOOK_LOG_FILE, [])
    rows = ''.join(f"<tr><td>{_safe_html(x.get('time'))}</td><td>{_safe_html(x.get('source'))}</td><td>{_safe_html(x.get('status'))}</td><td>{_safe_html(x.get('payload'))}</td></tr>" for x in logs[-100:][::-1]) or "<tr><td colspan='4'>No test logs yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase8_style()}</head><body><h1>Webhook Test Logs</h1>{_phase9_nav()}<div class='card'><form method='post' action='/phase9/webhooks/test?key={_safe_html(DASHBOARD_KEY)}'><input name='source' placeholder='shopify / rh_studio_ai / meta_ads'><br><br><textarea name='payload' placeholder='Paste sample webhook payload or note'></textarea><br><br><button>Save Test Log</button></form></div><br><table><tr><th>Time</th><th>Source</th><th>Status</th><th>Payload</th></tr>{rows}</table></body></html>""")


@app.post("/phase9/webhooks/test")
async def phase9_webhooks_test(key: str = "", source: str = Form("manual"), payload: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    logs = _json_load(PHASE9_WEBHOOK_LOG_FILE, [])
    logs.append({"time": datetime.utcnow().isoformat()+"Z", "source": source, "status": "received", "payload": payload[:1000]})
    _json_save(PHASE9_WEBHOOK_LOG_FILE, logs[-500:]); _audit("phase9_webhook_test_logged", {"source": source})
    return RedirectResponse(url=f"/phase9/webhooks?key={DASHBOARD_KEY}", status_code=303)


@app.get("/phase9/portal", response_class=HTMLResponse)
async def phase9_portal(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    s = _json_load(PHASE9_PORTAL_SETTINGS_FILE, {"enabled":"no", "portal_name":"RH Customer Portal", "public_upload":"no", "approval_required":"yes", "notes":"Customer portal will be separate after RH Business OS."})
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase8_style()}</head><body><h1>Customer Portal Bridge</h1>{_phase9_nav()}<div class='grid'><div class='card'><h2>Portal Settings</h2><form method='post' action='/phase9/portal/save?key={_safe_html(DASHBOARD_KEY)}'><label>Portal Name</label><input name='portal_name' value='{_safe_html(s.get('portal_name'))}'><br><br><label>Enabled</label><select name='enabled'><option>{_safe_html(s.get('enabled'))}</option><option>yes</option><option>no</option></select><br><br><label>Public Upload</label><select name='public_upload'><option>{_safe_html(s.get('public_upload'))}</option><option>yes</option><option>no</option></select><br><br><label>Approval Required</label><select name='approval_required'><option>{_safe_html(s.get('approval_required'))}</option><option>yes</option><option>no</option></select><br><br><label>Notes</label><textarea name='notes'>{_safe_html(s.get('notes'))}</textarea><br><br><button>Save Portal Settings</button></form></div><div class='card'><h2>Future Flow</h2><p>Customer uploads design → CRM creates design request → RH Studio AI processes file → customer approves quote/order.</p><p class='muted'>This is a safe planning bridge. Public portal should be built separately after CRM is stable.</p></div></div></body></html>""")


@app.post("/phase9/portal/save")
async def phase9_portal_save(key: str = "", portal_name: str = Form("RH Customer Portal"), enabled: str = Form("no"), public_upload: str = Form("no"), approval_required: str = Form("yes"), notes: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    _json_save(PHASE9_PORTAL_SETTINGS_FILE, {"portal_name": portal_name, "enabled": enabled, "public_upload": public_upload, "approval_required": approval_required, "notes": notes, "updated_at": datetime.utcnow().isoformat()+"Z"})
    _audit("phase9_portal_settings_saved", {"enabled": enabled})
    return RedirectResponse(url=f"/phase9/portal?key={DASHBOARD_KEY}", status_code=303)


@app.get("/phase9/performance", response_class=HTMLResponse)
async def phase9_performance(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    files = [CUSTOMERS_FILE, MESSAGES_FILE, SESSIONS_FILE, PHASE9_INTEGRATIONS_FILE, PHASE9_WEBHOOK_LOG_FILE, AUDIT_FILE]
    rows = ''
    total_size = 0
    for f in files:
        exists = os.path.exists(f)
        size = os.path.getsize(f) if exists else 0
        total_size += size
        rows += f"<tr><td>{_safe_html(f)}</td><td>{'yes' if exists else 'no'}</td><td>{round(size/1024,2)} KB</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase8_style()}</head><body><h1>Performance & Data Size</h1>{_phase9_nav()}<div class='cards'><div class='card'><div class='muted'>Tracked Files</div><div class='kpi'>{len(files)}</div></div><div class='card'><div class='muted'>Total Data Size</div><div class='kpi'>{round(total_size/1024,2)} KB</div></div></div><table><tr><th>File</th><th>Exists</th><th>Size</th></tr>{rows}</table><p class='muted'>For large production use, next major upgrade should move flat JSON to SQLite/PostgreSQL.</p></body></html>""")


@app.get("/phase9/launch", response_class=HTMLResponse)
async def phase9_launch(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    default = {
        "domain_ssl": {"label":"Domain and SSL ready", "done": False},
        "env_locked": {"label":"Production .env locked", "done": False},
        "backup_downloaded": {"label":"Latest backup downloaded", "done": False},
        "team_access": {"label":"Team access rules reviewed", "done": False},
        "whatsapp_templates": {"label":"WhatsApp templates approved", "done": False},
        "test_order": {"label":"One test lead → quote → order completed", "done": False},
        "mobile_check": {"label":"Mobile dashboard checked", "done": False},
        "training_done": {"label":"Staff training done", "done": False},
    }
    data = _json_load(PHASE9_LAUNCH_CHECKLIST_FILE, default)
    rows = ''.join(f"<tr><td>{_safe_html(v.get('label'))}</td><td>{'✅ Done' if v.get('done') else '⬜ Pending'}</td><td><form method='post' action='/phase9/launch/toggle?key={_safe_html(DASHBOARD_KEY)}'><input type='hidden' name='item_id' value='{_safe_html(k)}'><button>Toggle</button></form></td></tr>" for k,v in data.items())
    done = sum(1 for v in data.values() if v.get('done'))
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase8_style()}</head><body><h1>Phase 9 Launch Checklist</h1>{_phase9_nav()}<div class='card'><div class='muted'>Launch Progress</div><div class='kpi'>{done}/{len(data)}</div></div><br><table><tr><th>Item</th><th>Status</th><th>Action</th></tr>{rows}</table></body></html>""")


@app.post("/phase9/launch/toggle")
async def phase9_launch_toggle(key: str = "", item_id: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    default = _json_load(PHASE9_LAUNCH_CHECKLIST_FILE, {})
    if item_id in default:
        default[item_id]["done"] = not default[item_id].get("done", False)
        default[item_id]["updated_at"] = datetime.utcnow().isoformat()+"Z"
    _json_save(PHASE9_LAUNCH_CHECKLIST_FILE, default); _audit("phase9_launch_toggle", {"item_id": item_id})
    return RedirectResponse(url=f"/phase9/launch?key={DASHBOARD_KEY}", status_code=303)


@app.get("/phase9/export")
async def phase9_export(key: str = ""):
    if key != DASHBOARD_KEY: return JSONResponse(content={"error":"Access denied"}, status_code=401)
    return JSONResponse(content={"exported_at": datetime.utcnow().isoformat()+"Z", "version":"10.0.0", "integrations": _json_load(PHASE9_INTEGRATIONS_FILE, _phase9_default_integrations()), "portal": _json_load(PHASE9_PORTAL_SETTINGS_FILE, {}), "launch": _json_load(PHASE9_LAUNCH_CHECKLIST_FILE, {}), "note":"Phase 9 prepares integrations and launch readiness without exposing API secrets."})


# ── Phase 10: Production Ready Pack v10.0 ─────────────────────────────────────
# Safe production layer: settings, hardening checklist, file records, notifications,
# deployment checklist, test runs, and final launch control center.

PHASE10_SETTINGS_FILE = os.getenv("PHASE10_SETTINGS_FILE", "data/phase10_company_settings.json")
PHASE10_SECURITY_FILE = os.getenv("PHASE10_SECURITY_FILE", "data/phase10_security_checklist.json")
PHASE10_DEPLOY_FILE = os.getenv("PHASE10_DEPLOY_FILE", "data/phase10_deployment_checklist.json")
PHASE10_TESTS_FILE = os.getenv("PHASE10_TESTS_FILE", "data/phase10_test_runs.json")
PHASE10_FILES_FILE = os.getenv("PHASE10_FILES_FILE", "data/phase10_file_records.json")
PHASE10_NOTIFICATIONS_FILE = os.getenv("PHASE10_NOTIFICATIONS_FILE", "data/phase10_notifications.json")
PHASE10_DB_PLAN_FILE = os.getenv("PHASE10_DB_PLAN_FILE", "data/phase10_database_plan.json")


def _phase10_nav():
    k = _safe_html(DASHBOARD_KEY)
    return f"""
    <div class='nav'>
      <a href='/phase10?key={k}'>Control Center</a>
      <a href='/phase10/settings?key={k}'>Company Settings</a>
      <a href='/phase10/security?key={k}'>Security</a>
      <a href='/phase10/database?key={k}'>Database Plan</a>
      <a href='/phase10/files?key={k}'>File Manager</a>
      <a href='/phase10/notifications?key={k}'>Notifications</a>
      <a href='/phase10/deployment?key={k}'>Deployment</a>
      <a href='/phase10/tests?key={k}'>Testing</a>
      <a href='/dashboard?key={k}'>CRM</a>
    </div>
    """


def _phase10_default_security():
    return {
        "env_secrets": {"label":"All secrets are stored only in .env", "done": False},
        "dashboard_key_changed": {"label":"DASHBOARD_KEY changed from default", "done": False},
        "https_enabled": {"label":"HTTPS/SSL enabled on production domain", "done": False},
        "webhook_verified": {"label":"Meta webhook verified after deployment", "done": False},
        "input_validation": {"label":"Forms tested with invalid input", "done": False},
        "backup_policy": {"label":"Backup policy reviewed", "done": False},
        "team_access": {"label":"Team access and permission rules reviewed", "done": False},
        "audit_log": {"label":"Audit log checked", "done": False},
    }


def _phase10_default_deploy():
    return {
        "requirements": {"label":"requirements.txt installed", "done": False},
        "env": {"label":"Production .env added", "done": False},
        "data_folder": {"label":"data folder writable", "done": False},
        "server": {"label":"Server process running", "done": False},
        "domain": {"label":"Domain connected", "done": False},
        "ssl": {"label":"SSL certificate active", "done": False},
        "meta_callback": {"label":"Meta webhook callback URL updated", "done": False},
        "backup": {"label":"First production backup downloaded", "done": False},
        "staff_training": {"label":"Staff training completed", "done": False},
        "go_live": {"label":"Go-live approved", "done": False},
    }


def _phase10_default_db_plan():
    return {
        "current_storage":"JSON files",
        "recommended_next":"SQLite first, PostgreSQL later",
        "status":"planning",
        "tables":["customers","messages","quotes","orders","inventory","staff","tasks","audit_logs","files","notifications"],
        "notes":"v10.0 keeps JSON safe. Database migration should be done as separate tested branch before public scale.",
        "updated_at": datetime.utcnow().isoformat()+"Z",
    }


def _phase10_count_done(data):
    return sum(1 for v in data.values() if isinstance(v, dict) and v.get("done"))


@app.get("/phase10", response_class=HTMLResponse)
async def phase10_home(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    security = _json_load(PHASE10_SECURITY_FILE, _phase10_default_security())
    deploy = _json_load(PHASE10_DEPLOY_FILE, _phase10_default_deploy())
    tests = _json_load(PHASE10_TESTS_FILE, [])
    notifications = _json_load(PHASE10_NOTIFICATIONS_FILE, [])
    files = _json_load(PHASE10_FILES_FILE, [])
    sec_done, dep_done = _phase10_count_done(security), _phase10_count_done(deploy)
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase8_style()}</head><body><h1>Phase 10 Production Ready</h1>{_phase10_nav()}<div class='cards'><div class='card'><div class='muted'>Security</div><div class='kpi'>{sec_done}/{len(security)}</div></div><div class='card'><div class='muted'>Deployment</div><div class='kpi'>{dep_done}/{len(deploy)}</div></div><div class='card'><div class='muted'>Test Runs</div><div class='kpi'>{len(tests)}</div></div><div class='card'><div class='muted'>File Records</div><div class='kpi'>{len(files)}</div></div><div class='card'><div class='muted'>Notifications</div><div class='kpi'>{len(notifications)}</div></div></div><div class='card'><h2>Final Launch Rule</h2><p>Use this version as the final JSON-based production release. For heavy scale, migrate database in a separate tested upgrade.</p><p><b>Version:</b> v10.0.0</p></div></body></html>""")


@app.get("/phase10/settings", response_class=HTMLResponse)
async def phase10_settings(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    s = _json_load(PHASE10_SETTINGS_FILE, {"company_name":"Rhinestone Heritage", "gst":"", "address":"", "phone":"", "email":"", "bank_details":"", "invoice_footer":"Thank you for your business.", "currency":"INR"})
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase8_style()}</head><body><h1>Company Settings</h1>{_phase10_nav()}<div class='card'><form method='post' action='/phase10/settings/save?key={_safe_html(DASHBOARD_KEY)}'><input name='company_name' value='{_safe_html(s.get('company_name'))}' placeholder='Company Name'><br><br><input name='gst' value='{_safe_html(s.get('gst'))}' placeholder='GST Number'><br><br><input name='phone' value='{_safe_html(s.get('phone'))}' placeholder='Phone'><br><br><input name='email' value='{_safe_html(s.get('email'))}' placeholder='Email'><br><br><input name='currency' value='{_safe_html(s.get('currency'))}' placeholder='Currency'><br><br><textarea name='address' placeholder='Address'>{_safe_html(s.get('address'))}</textarea><br><br><textarea name='bank_details' placeholder='Bank Details'>{_safe_html(s.get('bank_details'))}</textarea><br><br><textarea name='invoice_footer' placeholder='Invoice Footer'>{_safe_html(s.get('invoice_footer'))}</textarea><br><br><button>Save Settings</button></form></div></body></html>""")


@app.post("/phase10/settings/save")
async def phase10_settings_save(key: str = "", company_name: str = Form(""), gst: str = Form(""), phone: str = Form(""), email: str = Form(""), currency: str = Form("INR"), address: str = Form(""), bank_details: str = Form(""), invoice_footer: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    _json_save(PHASE10_SETTINGS_FILE, {"company_name":company_name, "gst":gst, "phone":phone, "email":email, "currency":currency, "address":address, "bank_details":bank_details, "invoice_footer":invoice_footer, "updated_at":datetime.utcnow().isoformat()+"Z"})
    _audit("phase10_settings_saved", {"company_name": company_name})
    return RedirectResponse(url=f"/phase10/settings?key={DASHBOARD_KEY}", status_code=303)


def _phase10_checklist_page(title, file_path, default_data, toggle_url):
    data = _json_load(file_path, default_data)
    rows = ''.join(f"<tr><td>{_safe_html(v.get('label'))}</td><td>{'✅ Done' if v.get('done') else '⬜ Pending'}</td><td><form method='post' action='{toggle_url}?key={_safe_html(DASHBOARD_KEY)}'><input type='hidden' name='item_id' value='{_safe_html(k)}'><button>Toggle</button></form></td></tr>" for k,v in data.items())
    done = _phase10_count_done(data)
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase8_style()}</head><body><h1>{_safe_html(title)}</h1>{_phase10_nav()}<div class='card'><div class='muted'>Progress</div><div class='kpi'>{done}/{len(data)}</div></div><br><table><tr><th>Item</th><th>Status</th><th>Action</th></tr>{rows}</table></body></html>""")


@app.get("/phase10/security", response_class=HTMLResponse)
async def phase10_security(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    return _phase10_checklist_page("Security Hardening", PHASE10_SECURITY_FILE, _phase10_default_security(), "/phase10/security/toggle")


@app.post("/phase10/security/toggle")
async def phase10_security_toggle(key: str = "", item_id: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(PHASE10_SECURITY_FILE, _phase10_default_security())
    if item_id in data:
        data[item_id]["done"] = not data[item_id].get("done", False); data[item_id]["updated_at"] = datetime.utcnow().isoformat()+"Z"
    _json_save(PHASE10_SECURITY_FILE, data); _audit("phase10_security_toggle", {"item_id": item_id})
    return RedirectResponse(url=f"/phase10/security?key={DASHBOARD_KEY}", status_code=303)


@app.get("/phase10/deployment", response_class=HTMLResponse)
async def phase10_deployment(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    return _phase10_checklist_page("Deployment Checklist", PHASE10_DEPLOY_FILE, _phase10_default_deploy(), "/phase10/deployment/toggle")


@app.post("/phase10/deployment/toggle")
async def phase10_deployment_toggle(key: str = "", item_id: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    data = _json_load(PHASE10_DEPLOY_FILE, _phase10_default_deploy())
    if item_id in data:
        data[item_id]["done"] = not data[item_id].get("done", False); data[item_id]["updated_at"] = datetime.utcnow().isoformat()+"Z"
    _json_save(PHASE10_DEPLOY_FILE, data); _audit("phase10_deployment_toggle", {"item_id": item_id})
    return RedirectResponse(url=f"/phase10/deployment?key={DASHBOARD_KEY}", status_code=303)


@app.get("/phase10/database", response_class=HTMLResponse)
async def phase10_database(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    d = _json_load(PHASE10_DB_PLAN_FILE, _phase10_default_db_plan())
    rows = ''.join(f"<tr><td>{_safe_html(t)}</td><td>planned</td></tr>" for t in d.get('tables', []))
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase8_style()}</head><body><h1>Database Migration Plan</h1>{_phase10_nav()}<div class='grid'><div class='card'><h2>Status</h2><p><b>Current:</b> {_safe_html(d.get('current_storage'))}</p><p><b>Recommended:</b> {_safe_html(d.get('recommended_next'))}</p><p><b>Status:</b> {_safe_html(d.get('status'))}</p><p class='muted'>{_safe_html(d.get('notes'))}</p></div><div class='card'><h2>Update Plan</h2><form method='post' action='/phase10/database/save?key={_safe_html(DASHBOARD_KEY)}'><select name='status'><option>{_safe_html(d.get('status'))}</option><option>planning</option><option>ready_for_sqlite</option><option>ready_for_postgres</option><option>done</option></select><br><br><textarea name='notes'>{_safe_html(d.get('notes'))}</textarea><br><br><button>Save Plan</button></form></div></div><br><table><tr><th>Table</th><th>Status</th></tr>{rows}</table></body></html>""")


@app.post("/phase10/database/save")
async def phase10_database_save(key: str = "", status: str = Form("planning"), notes: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    d = _json_load(PHASE10_DB_PLAN_FILE, _phase10_default_db_plan()); d["status"] = status; d["notes"] = notes; d["updated_at"] = datetime.utcnow().isoformat()+"Z"
    _json_save(PHASE10_DB_PLAN_FILE, d); _audit("phase10_database_plan_saved", {"status": status})
    return RedirectResponse(url=f"/phase10/database?key={DASHBOARD_KEY}", status_code=303)


@app.get("/phase10/files", response_class=HTMLResponse)
async def phase10_files(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    items = _json_load(PHASE10_FILES_FILE, [])
    rows = ''.join(f"<tr><td>{_safe_html(x.get('title'))}</td><td>{_safe_html(x.get('type'))}</td><td>{_safe_html(x.get('customer_phone'))}</td><td>{_safe_html(x.get('location'))}</td><td>{_safe_html(x.get('created_at'))}</td></tr>" for x in items[::-1]) or "<tr><td colspan='5'>No files recorded yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase8_style()}</head><body><h1>File Manager Records</h1>{_phase10_nav()}<div class='card'><form method='post' action='/phase10/files/add?key={_safe_html(DASHBOARD_KEY)}'><input name='title' placeholder='File title'><br><br><input name='type' placeholder='quote / design / invoice / proof'><br><br><input name='customer_phone' placeholder='Customer phone'><br><br><input name='location' placeholder='Drive link or local path'><br><br><button>Add File Record</button></form></div><br><table><tr><th>Title</th><th>Type</th><th>Customer</th><th>Location</th><th>Created</th></tr>{rows}</table></body></html>""")


@app.post("/phase10/files/add")
async def phase10_files_add(key: str = "", title: str = Form(""), type: str = Form(""), customer_phone: str = Form(""), location: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    items = _json_load(PHASE10_FILES_FILE, [])
    items.append({"id": f"FILE-{len(items)+1:05d}", "title": title, "type": type, "customer_phone": customer_phone, "location": location, "created_at": datetime.utcnow().isoformat()+"Z"})
    _json_save(PHASE10_FILES_FILE, items[-2000:]); _audit("phase10_file_record_added", {"title": title})
    return RedirectResponse(url=f"/phase10/files?key={DASHBOARD_KEY}", status_code=303)


@app.get("/phase10/notifications", response_class=HTMLResponse)
async def phase10_notifications(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    items = _json_load(PHASE10_NOTIFICATIONS_FILE, [])
    rows = ''.join(f"<tr><td>{_safe_html(x.get('time'))}</td><td>{_safe_html(x.get('title'))}</td><td>{_safe_html(x.get('message'))}</td><td>{_safe_html(x.get('status'))}</td></tr>" for x in items[::-1]) or "<tr><td colspan='4'>No notifications yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase8_style()}</head><body><h1>Notification Center</h1>{_phase10_nav()}<div class='card'><form method='post' action='/phase10/notifications/add?key={_safe_html(DASHBOARD_KEY)}'><input name='title' placeholder='Notification title'><br><br><textarea name='message' placeholder='Message'></textarea><br><br><select name='status'><option>open</option><option>done</option></select><br><br><button>Add Notification</button></form></div><br><table><tr><th>Time</th><th>Title</th><th>Message</th><th>Status</th></tr>{rows}</table></body></html>""")


@app.post("/phase10/notifications/add")
async def phase10_notifications_add(key: str = "", title: str = Form(""), message: str = Form(""), status: str = Form("open")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    items = _json_load(PHASE10_NOTIFICATIONS_FILE, [])
    items.append({"time": datetime.utcnow().isoformat()+"Z", "title": title, "message": message, "status": status})
    _json_save(PHASE10_NOTIFICATIONS_FILE, items[-1000:]); _audit("phase10_notification_added", {"title": title})
    return RedirectResponse(url=f"/phase10/notifications?key={DASHBOARD_KEY}", status_code=303)


@app.get("/phase10/tests", response_class=HTMLResponse)
async def phase10_tests(key: str = ""):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    tests = _json_load(PHASE10_TESTS_FILE, [])
    rows = ''.join(f"<tr><td>{_safe_html(x.get('time'))}</td><td>{_safe_html(x.get('module'))}</td><td>{_safe_html(x.get('result'))}</td><td>{_safe_html(x.get('notes'))}</td></tr>" for x in tests[::-1]) or "<tr><td colspan='4'>No test runs yet.</td></tr>"
    return HTMLResponse(content=f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{_phase8_style()}</head><body><h1>Production Testing</h1>{_phase10_nav()}<div class='card'><form method='post' action='/phase10/tests/add?key={_safe_html(DASHBOARD_KEY)}'><input name='module' placeholder='CRM / Quote / Order / WhatsApp'><br><br><select name='result'><option>pass</option><option>fail</option><option>needs_fix</option></select><br><br><textarea name='notes' placeholder='Test notes'></textarea><br><br><button>Save Test Run</button></form></div><br><table><tr><th>Time</th><th>Module</th><th>Result</th><th>Notes</th></tr>{rows}</table></body></html>""")


@app.post("/phase10/tests/add")
async def phase10_tests_add(key: str = "", module: str = Form(""), result: str = Form("pass"), notes: str = Form("")):
    if key != DASHBOARD_KEY: return HTMLResponse(content="Access Denied", status_code=401)
    tests = _json_load(PHASE10_TESTS_FILE, [])
    tests.append({"time": datetime.utcnow().isoformat()+"Z", "module": module, "result": result, "notes": notes})
    _json_save(PHASE10_TESTS_FILE, tests[-1000:]); _audit("phase10_test_added", {"module": module, "result": result})
    return RedirectResponse(url=f"/phase10/tests?key={DASHBOARD_KEY}", status_code=303)


@app.get("/phase10/export")
async def phase10_export(key: str = ""):
    if key != DASHBOARD_KEY: return JSONResponse(content={"error":"Access denied"}, status_code=401)
    return JSONResponse(content={
        "exported_at": datetime.utcnow().isoformat()+"Z",
        "version":"10.0.0",
        "company_settings": _json_load(PHASE10_SETTINGS_FILE, {}),
        "security": _json_load(PHASE10_SECURITY_FILE, _phase10_default_security()),
        "deployment": _json_load(PHASE10_DEPLOY_FILE, _phase10_default_deploy()),
        "database_plan": _json_load(PHASE10_DB_PLAN_FILE, _phase10_default_db_plan()),
        "files": _json_load(PHASE10_FILES_FILE, []),
        "notifications": _json_load(PHASE10_NOTIFICATIONS_FILE, []),
        "tests": _json_load(PHASE10_TESTS_FILE, []),
    })


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/")
async def health():
    return {
        "service": "RH Business OS — WhatsApp AI Bot",
        "version": "10.2.0",
        "status":  "running",
        "phase": "Phase 10 Production Ready",
    }

"""
RH Business OS — WhatsApp AI Bot v3.0
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
    title="RH Business OS — WhatsApp AI Bot v3.0",
    description="Conversation flow engine + Basic CRM for Rhinestone Heritage",
    version="3.0.0",
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
        return HTMLResponse(
            content="""
            <!doctype html>
            <html><head><title>Access Denied</title></head>
            <body style="font-family:Arial;padding:40px;background:#f7f7f7;">
                <div style="max-width:500px;margin:auto;background:white;padding:30px;border-radius:14px;text-align:center;">
                    <h2>Access Denied</h2>
                    <p>Please open dashboard with your secure key.</p>
                    <p style="color:#777;">Example: /dashboard?key=YOUR_KEY</p>
                </div>
            </body></html>
            """,
            status_code=401,
        )
    customers = _load_customers()
    rows = list(customers.values())

    total = len(rows)
    wholesalers = sum(1 for c in rows if c.get("buyer_type") == "wholesaler")
    retailers = sum(1 for c in rows if c.get("buyer_type") == "retailer")
    personal = sum(1 for c in rows if c.get("buyer_type") == "personal")
    qualified = sum(1 for c in rows if c.get("lead_status") == "QUALIFIED_LEAD")
    website_sent = sum(1 for c in rows if c.get("lead_status") == "WEBSITE_SENT")
    hot_leads = sum(1 for c in rows if c.get("is_hot_lead") is True)
    today_followups = sum(1 for c in rows if _followup_status(c) == "today")
    missed_followups = sum(1 for c in rows if _followup_status(c) == "missed")
    upcoming_followups = sum(1 for c in rows if _followup_status(c) == "upcoming")
    followups_sent = sum(1 for c in rows if c.get("last_followup_sent_at"))
    assigned_leads = sum(1 for c in rows if c.get("assigned_to"))
    unassigned_leads = sum(1 for c in rows if not c.get("assigned_to"))
    open_tasks = sum(1 for c in rows if c.get("task_text") and c.get("task_status") != "DONE")
    done_tasks = sum(1 for c in rows if c.get("task_status") == "DONE")
    quote_pending = sum(1 for c in rows if c.get("pipeline_stage") == "QUOTE_PENDING")
    quote_sent = sum(1 for c in rows if c.get("pipeline_stage") == "QUOTE_SENT")
    order_confirmed = sum(1 for c in rows if c.get("pipeline_stage") == "ORDER_CONFIRMED")

    query = (q or "").strip().lower()

    if filter == "wholesaler":
        rows = [c for c in rows if c.get("buyer_type") == "wholesaler"]
    elif filter == "retailer":
        rows = [c for c in rows if c.get("buyer_type") == "retailer"]
    elif filter == "personal":
        rows = [c for c in rows if c.get("buyer_type") == "personal"]
    elif filter == "qualified":
        rows = [c for c in rows if c.get("lead_status") == "QUALIFIED_LEAD"]
    elif filter == "website_sent":
        rows = [c for c in rows if c.get("lead_status") == "WEBSITE_SENT"]
    elif filter == "hot":
        rows = [c for c in rows if c.get("is_hot_lead") is True]
    elif filter == "followup_today":
        rows = [c for c in rows if _followup_status(c) == "today"]
    elif filter == "followup_missed":
        rows = [c for c in rows if _followup_status(c) == "missed"]
    elif filter == "followup_upcoming":
        rows = [c for c in rows if _followup_status(c) == "upcoming"]
    elif filter == "followup_sent":
        rows = [c for c in rows if c.get("last_followup_sent_at")]
    elif filter == "assigned":
        rows = [c for c in rows if c.get("assigned_to")]
    elif filter == "unassigned":
        rows = [c for c in rows if not c.get("assigned_to")]
    elif filter == "task_open":
        rows = [c for c in rows if c.get("task_text") and c.get("task_status") != "DONE"]
    elif filter == "task_done":
        rows = [c for c in rows if c.get("task_status") == "DONE"]
    elif filter == "quote_pending":
        rows = [c for c in rows if c.get("pipeline_stage") == "QUOTE_PENDING"]
    elif filter == "quote_sent":
        rows = [c for c in rows if c.get("pipeline_stage") == "QUOTE_SENT"]
    elif filter == "order_confirmed":
        rows = [c for c in rows if c.get("pipeline_stage") == "ORDER_CONFIRMED"]
    elif filter.startswith("pipeline_"):
        stage_name = filter.replace("pipeline_", "", 1).upper()
        rows = [c for c in rows if str(c.get("pipeline_stage", "NEW")).upper() == stage_name]
    elif filter.startswith("assigned_"):
        assigned_name = filter.replace("assigned_", "", 1).lower()
        rows = [c for c in rows if str(c.get("assigned_to", "")).lower() == assigned_name]

    if query:
        rows = [
            c for c in rows
            if query in str(c.get("phone_number", "")).lower()
            or query in str(c.get("buyer_type", "")).lower()
            or query in str(c.get("lead_status", "")).lower()
            or query in str(c.get("last_message", "")).lower()
            or query in str(c.get("notes", "")).lower()
            or query in str(c.get("followup_note", "")).lower()
            or query in str(c.get("assigned_to", "")).lower()
            or query in str(c.get("task_text", "")).lower()
            or query in str(c.get("pipeline_stage", "")).lower()
        ]

    def esc(value):
        if value is None:
            return ""
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(chr(34), "&quot;")

    def status_class(status):
        status = status or ""
        if status == "QUALIFIED_LEAD":
            return "qualified"
        if status == "WEBSITE_SENT":
            return "website"
        if status == "FOLLOW_UP_SENT":
            return "qualified"
        if status in ("WAITING_DESIGN", "WAITING_MOQ", "WAITING_BUYER_TYPE"):
            return "waiting"
        return "new"

    def followup_class(c):
        st = _followup_status(c)
        return {"today":"follow_today", "missed":"follow_missed", "upcoming":"follow_upcoming", "done":"follow_done"}.get(st, "follow_none")

    def short_date(value):
        if not value:
            return ""
        return value.replace("T", " ").replace("Z", "")[:19]

    def filter_link(label, key):
        active = "active" if filter == key else ""
        return f'<a class="filter {active}" href="/dashboard?key={esc(DASHBOARD_KEY)}&filter={key}&q={esc(q)}">{label}</a>'

    rows_html = ""
    for c in sorted(rows, key=lambda x: x.get("last_seen", ""), reverse=True):
        status = c.get("lead_status") or ""
        rows_html += f"""
        <tr>
            <td class="phone"><a style="color:#111;font-weight:700;text-decoration:none;" href="/customer/{esc(c.get('phone_number'))}?key={esc(DASHBOARD_KEY)}">{esc(c.get("phone_number"))}</a></td>
            <td><span class="pill buyer">{esc(c.get("buyer_type") or "unknown")}</span></td>
            <td><span class="pill {status_class(status)}">{esc(status)}</span></td>
            <td><span class="pill assigned">{esc(c.get("assigned_to") or "Unassigned")}</span></td>
            <td><span class="pill pipeline">{esc(c.get("pipeline_stage") or "NEW")}</span></td>
            <td><span class="pill task">{esc((c.get("task_status") or "") if c.get("task_text") else "No Task")}</span></td>
            <td class="lastmsg">{esc(c.get("last_message"))}</td>
            <td>{esc(c.get("message_count"))}</td>
            <td>{esc(short_date(c.get("first_seen")))}</td>
            <td>{esc(short_date(c.get("last_seen")))}</td>
            <td><span class="pill {followup_class(c)}">{esc(_format_followup(c.get("followup_at")) or "Not set")}</span></td>
            <td>{esc(short_date(c.get("last_followup_sent_at")))}</td>
        </tr>
        """

    if not rows:
        main_content = '<div class="empty">No matching leads found.</div>'
    else:
        main_content = f"""
        <table>
            <thead>
                <tr>
                    <th>Phone (click)</th>
                    <th>Buyer Type</th>
                    <th>Status</th>
                    <th>Assigned To</th>
                    <th>Pipeline</th>
                    <th>Task</th>
                    <th>Last Message</th>
                    <th>Messages</th>
                    <th>First Seen</th>
                    <th>Last Seen</th>
                    <th>Follow-up</th>
                    <th>Last Sent</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        """

    html = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta http-equiv="refresh" content="30">
        <title>RH Business OS CRM</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7f7;
                margin: 0;
                padding: 24px;
                color: #111;
            }}
            .header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 22px;
            }}
            h1 {{ margin: 0; font-size: 28px; }}
            .subtitle {{ color: #666; margin-top: 6px; }}
            .top-actions {{ display: flex; gap: 10px; align-items: center; }}
            .refresh {{
                color: #111;
                text-decoration: none;
                background: white;
                padding: 10px 14px;
                border-radius: 10px;
                border: 1px solid #ddd;
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
                gap: 14px;
                margin-bottom: 20px;
            }}
            .card {{
                background: white;
                border: 1px solid #e5e5e5;
                border-radius: 14px;
                padding: 18px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.04);
            }}
            .card-title {{ color: #666; font-size: 13px; }}
            .card-value {{ font-size: 28px; font-weight: bold; margin-top: 8px; }}
            .toolbar {{
                display: flex;
                gap: 12px;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 16px;
                flex-wrap: wrap;
            }}
            .search {{ display: flex; gap: 8px; flex: 1; min-width: 260px; }}
            input {{
                width: 100%;
                padding: 12px 14px;
                border: 1px solid #ddd;
                border-radius: 10px;
                font-size: 14px;
            }}
            button {{
                padding: 12px 16px;
                border: 0;
                background: #111;
                color: white;
                border-radius: 10px;
                cursor: pointer;
            }}
            .filters {{ display: flex; gap: 8px; flex-wrap: wrap; }}
            .filter {{
                text-decoration: none;
                color: #111;
                background: white;
                border: 1px solid #ddd;
                padding: 9px 12px;
                border-radius: 999px;
                font-size: 13px;
            }}
            .filter.active {{ background: #111; color: white; border-color: #111; }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: white;
                border-radius: 14px;
                overflow: hidden;
                box-shadow: 0 2px 8px rgba(0,0,0,0.04);
            }}
            th, td {{
                padding: 12px 14px;
                border-bottom: 1px solid #eee;
                text-align: left;
                font-size: 14px;
                vertical-align: top;
            }}
            th {{ background: #111; color: white; font-weight: 600; }}
            .phone {{ font-weight: 700; }}
            .lastmsg {{ max-width: 520px; }}
            .pill {{
                display: inline-block;
                padding: 5px 9px;
                border-radius: 999px;
                font-size: 12px;
                font-weight: 600;
                background: #eee;
            }}
            .buyer {{ background: #e8f0ff; }}
            .assigned {{ background:#f3e8ff; color:#6b21a8; }}
            .pipeline {{ background:#e0f2fe; color:#075985; }}
            .task {{ background:#fef3c7; color:#92400e; }}
            .qualified {{ background: #dcfce7; color: #166534; }}
            .website {{ background: #fff7ed; color: #9a3412; }}
            .waiting {{ background: #fef9c3; color: #854d0e; }}
            .new {{ background: #eef2ff; color: #3730a3; }}
            .follow_today {{ background:#dbeafe; color:#1d4ed8; }}
            .follow_missed {{ background:#fee2e2; color:#991b1b; }}
            .follow_upcoming {{ background:#dcfce7; color:#166534; }}
            .follow_done {{ background:#e5e7eb; color:#374151; }}
            .follow_none {{ background:#f3f4f6; color:#6b7280; }}
            .empty {{
                background: white;
                padding: 30px;
                border-radius: 14px;
                text-align: center;
                color: #666;
            }}
            @media (max-width: 700px) {{
                body {{ padding: 14px; }}
                .header {{ align-items: flex-start; flex-direction: column; gap: 12px; }}
                table {{ display: block; overflow-x: auto; }}
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <div>
                <h1>RH Business OS CRM</h1>
                <div class="subtitle">WhatsApp leads dashboard • Auto-refresh every 30 seconds</div>
            </div>
            <div class="top-actions">
                <a class="refresh" href="/calendar?key={esc(DASHBOARD_KEY)}">Calendar</a>
                <a class="refresh" href="/team?key={esc(DASHBOARD_KEY)}">Team</a>
                <a class="refresh" href="/backup?key={esc(DASHBOARD_KEY)}">Backup</a>
                <a class="refresh" href="/dashboard/export?key={esc(DASHBOARD_KEY)}">Download CSV</a>
                <a class="refresh" href="/dashboard?key={esc(DASHBOARD_KEY)}">Reset</a>
                <a class="refresh" href="/dashboard?key={esc(DASHBOARD_KEY)}&filter={esc(filter)}&q={esc(q)}">Refresh</a>
            </div>
        </div>

        <div class="cards">
            <div class="card"><div class="card-title">Total Leads</div><div class="card-value">{total}</div></div>
            <div class="card"><div class="card-title">Wholesaler / Manufacturer</div><div class="card-value">{wholesalers}</div></div>
            <div class="card"><div class="card-title">Retailer</div><div class="card-value">{retailers}</div></div>
            <div class="card"><div class="card-title">Personal Buyer</div><div class="card-value">{personal}</div></div>
            <div class="card"><div class="card-title">Qualified Leads</div><div class="card-value">{qualified}</div></div>
            <div class="card"><div class="card-title">Website Sent</div><div class="card-value">{website_sent}</div></div>
            <div class="card"><div class="card-title">Hot Leads</div><div class="card-value">{hot_leads}</div></div>
            <div class="card"><div class="card-title">Today Follow-ups</div><div class="card-value">{today_followups}</div></div>
            <div class="card"><div class="card-title">Missed Follow-ups</div><div class="card-value">{missed_followups}</div></div>
            <div class="card"><div class="card-title">Upcoming Follow-ups</div><div class="card-value">{upcoming_followups}</div></div>
            <div class="card"><div class="card-title">Follow-ups Sent</div><div class="card-value">{followups_sent}</div></div>
            <div class="card"><div class="card-title">Assigned Leads</div><div class="card-value">{assigned_leads}</div></div>
            <div class="card"><div class="card-title">Unassigned Leads</div><div class="card-value">{unassigned_leads}</div></div>
            <div class="card"><div class="card-title">Open Tasks</div><div class="card-value">{open_tasks}</div></div>
            <div class="card"><div class="card-title">Done Tasks</div><div class="card-value">{done_tasks}</div></div>
            <div class="card"><div class="card-title">Quote Pending</div><div class="card-value">{quote_pending}</div></div>
            <div class="card"><div class="card-title">Quote Sent</div><div class="card-value">{quote_sent}</div></div>
            <div class="card"><div class="card-title">Orders Confirmed</div><div class="card-value">{order_confirmed}</div></div>
        </div>

        <div class="toolbar">
            <form class="search" method="get" action="/dashboard">
                <input type="hidden" name="key" value="{esc(DASHBOARD_KEY)}">
                <input type="hidden" name="filter" value="{esc(filter)}">
                <input name="q" value="{esc(q)}" placeholder="Search phone, buyer type, status, message...">
                <button type="submit">Search</button>
            </form>

            <div class="filters">
                {filter_link("All", "all")}
                {filter_link("Wholesaler", "wholesaler")}
                {filter_link("Retailer", "retailer")}
                {filter_link("Personal", "personal")}
                {filter_link("Qualified", "qualified")}
                {filter_link("Website Sent", "website_sent")}
                {filter_link("Hot Leads", "hot")}
                {filter_link("Today Follow-ups", "followup_today")}
                {filter_link("Missed Follow-ups", "followup_missed")}
                {filter_link("Upcoming Follow-ups", "followup_upcoming")}
                {filter_link("Follow-up Sent", "followup_sent")}
                {filter_link("Assigned", "assigned")}
                {filter_link("Unassigned", "unassigned")}
                {filter_link("Open Tasks", "task_open")}
                {filter_link("Done Tasks", "task_done")}
                {filter_link("Quote Pending", "quote_pending")}
                {filter_link("Quote Sent", "quote_sent")}
                {filter_link("Order Confirmed", "order_confirmed")}
                {"".join(filter_link(name, "assigned_" + name.lower()) for name in ASSIGNEES)}
            </div>
        </div>

        {main_content}
    </body>
    </html>
    """
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


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/")
async def health():
    return {
        "service": "RH Business OS — WhatsApp AI Bot",
        "version": "3.0.0",
        "status":  "running",
    }

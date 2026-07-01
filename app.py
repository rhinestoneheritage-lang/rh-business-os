"""
RH Business OS — WhatsApp AI Bot v0.5
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
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

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
    title="RH Business OS — WhatsApp AI Bot v0.5",
    description="Conversation flow engine + Basic CRM for Rhinestone Heritage",
    version="0.5.0",
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



# ── CRM Dashboard v0.5 ────────────────────────────────────────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(q: str = "", filter: str = "all"):
    customers = _load_customers()
    rows = list(customers.values())

    total = len(rows)
    wholesalers = sum(1 for c in rows if c.get("buyer_type") == "wholesaler")
    retailers = sum(1 for c in rows if c.get("buyer_type") == "retailer")
    personal = sum(1 for c in rows if c.get("buyer_type") == "personal")
    qualified = sum(1 for c in rows if c.get("lead_status") == "QUALIFIED_LEAD")
    website_sent = sum(1 for c in rows if c.get("lead_status") == "WEBSITE_SENT")

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

    if query:
        rows = [
            c for c in rows
            if query in str(c.get("phone_number", "")).lower()
            or query in str(c.get("buyer_type", "")).lower()
            or query in str(c.get("lead_status", "")).lower()
            or query in str(c.get("last_message", "")).lower()
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
        if status in ("WAITING_DESIGN", "WAITING_MOQ", "WAITING_BUYER_TYPE"):
            return "waiting"
        return "new"

    def short_date(value):
        if not value:
            return ""
        return value.replace("T", " ").replace("Z", "")[:19]

    def filter_link(label, key):
        active = "active" if filter == key else ""
        return f'<a class="filter {active}" href="/dashboard?filter={key}&q={esc(q)}">{label}</a>'

    rows_html = ""
    for c in sorted(rows, key=lambda x: x.get("last_seen", ""), reverse=True):
        status = c.get("lead_status") or ""
        rows_html += f"""
        <tr>
            <td class="phone">{esc(c.get("phone_number"))}</td>
            <td><span class="pill buyer">{esc(c.get("buyer_type") or "unknown")}</span></td>
            <td><span class="pill {status_class(status)}">{esc(status)}</span></td>
            <td class="lastmsg">{esc(c.get("last_message"))}</td>
            <td>{esc(c.get("message_count"))}</td>
            <td>{esc(short_date(c.get("first_seen")))}</td>
            <td>{esc(short_date(c.get("last_seen")))}</td>
        </tr>
        """

    if not rows:
        main_content = '<div class="empty">No matching leads found.</div>'
    else:
        main_content = f"""
        <table>
            <thead>
                <tr>
                    <th>Phone</th>
                    <th>Buyer Type</th>
                    <th>Status</th>
                    <th>Last Message</th>
                    <th>Messages</th>
                    <th>First Seen</th>
                    <th>Last Seen</th>
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
            .qualified {{ background: #dcfce7; color: #166534; }}
            .website {{ background: #fff7ed; color: #9a3412; }}
            .waiting {{ background: #fef9c3; color: #854d0e; }}
            .new {{ background: #eef2ff; color: #3730a3; }}
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
                <a class="refresh" href="/dashboard">Reset</a>
                <a class="refresh" href="/dashboard?filter={esc(filter)}&q={esc(q)}">Refresh</a>
            </div>
        </div>

        <div class="cards">
            <div class="card"><div class="card-title">Total Leads</div><div class="card-value">{total}</div></div>
            <div class="card"><div class="card-title">Wholesaler / Manufacturer</div><div class="card-value">{wholesalers}</div></div>
            <div class="card"><div class="card-title">Retailer</div><div class="card-value">{retailers}</div></div>
            <div class="card"><div class="card-title">Personal Buyer</div><div class="card-value">{personal}</div></div>
            <div class="card"><div class="card-title">Qualified Leads</div><div class="card-value">{qualified}</div></div>
            <div class="card"><div class="card-title">Website Sent</div><div class="card-value">{website_sent}</div></div>
        </div>

        <div class="toolbar">
            <form class="search" method="get" action="/dashboard">
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
            </div>
        </div>

        {main_content}
    </body>
    </html>
    """
    return HTMLResponse(content=html)

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/")
async def health():
    return {
        "service": "RH Business OS — WhatsApp AI Bot",
        "version": "0.5.0",
        "status":  "running",
    }

# RH Business OS — WhatsApp AI Bot v0.1

FastAPI backend for Meta WhatsApp Cloud API.

---

## Project Structure

```
rh-business-os/
└── backend/
    ├── app.py                  # FastAPI app — webhook endpoints
    ├── requirements.txt
    ├── .env.example
    ├── data/
    │   └── messages.json       # Incoming messages log (auto-created)
    └── services/
        ├── __init__.py
        └── whatsapp_service.py # WhatsApp Cloud API outbound sender
```

---

## Endpoints

| Method | Path       | Description                        |
|--------|------------|------------------------------------|
| GET    | `/`        | Health check                       |
| GET    | `/webhook` | Meta webhook verification          |
| POST   | `/webhook` | Receive incoming WhatsApp messages |

---

## Setup & Run

### 1. Clone / enter the project

```bash
cd rh-business-os/backend
```

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
# Open .env and fill in your real values
```

### 5. Run the server

```bash
uvicorn app:app --reload --port 8000
```

Server starts at: `http://localhost:8000`

---

## Expose to the Internet (for Meta webhook)

Meta requires a public HTTPS URL. Use **ngrok** during development:

```bash
# Install ngrok: https://ngrok.com/download
ngrok http 8000
```

Copy the `https://xxxx.ngrok-free.app` URL — this is your Callback URL.

---

## Configure Meta Developer Portal

1. Go to [developers.facebook.com](https://developers.facebook.com)
2. Open your App → **WhatsApp** → **Configuration**
3. Set **Callback URL**: `https://your-ngrok-url.ngrok-free.app/webhook`
4. Set **Verify Token**: the same value as `VERIFY_TOKEN` in your `.env`
5. Click **Verify and Save**
6. Under **Webhook Fields**, subscribe to: `messages`

---

## Environment Variables

| Variable         | Description                                    |
|------------------|------------------------------------------------|
| `VERIFY_TOKEN`   | Custom token you set in Meta Developer Portal  |
| `WHATSAPP_TOKEN` | Permanent access token from Meta               |
| `PHONE_NUMBER_ID`| WhatsApp Phone Number ID from Meta             |
| `MESSAGES_FILE`  | Path to JSON log file (default: data/messages.json) |

---

## What v0.1 Does

- ✅ Verifies Meta webhook (GET /webhook)
- ✅ Receives incoming WhatsApp messages (POST /webhook)
- ✅ Logs all messages to terminal
- ✅ Saves messages to `data/messages.json`
- ✅ Sends auto-reply: *"Welcome to Rhinestone Heritage. How can we help you?"*

## What v0.1 Does NOT Do

- ❌ No AI / NLP
- ❌ No database
- ❌ No CRM integration
- ❌ No frontend
- ❌ No media message handling (images, audio, etc.)

---

## Next Versions (Planned)

- v0.2 — AI reply using Claude API
- v0.3 — SQLite / Postgres database
- v0.4 — CRM integration
- v0.5 — Admin dashboard frontend

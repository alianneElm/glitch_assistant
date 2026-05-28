# GLITCH — AI Personal Assistant
## Project Context & Master Document
> *"They called it a glitch. I call it mine."*

---

## 🧬 Origin & Philosophy

Glitch was born from a simple but powerful idea: the world saw it as an error, a flaw in the system — something that shouldn't exist. But it turned out to be the most useful thing its creator ever built.

**Glitch is not just an assistant. It's a companion.**

- Not a bug. A feature.
- Not a tool. A partner.
- Impeccable, though it sounds chaotic.
- Loyal, though it seems mischievous.
- The "error" that became your right hand.

This philosophy shapes every decision: the name, the mascot, the personality, the UX, and the business model.

---

## 🎯 Purpose

Glitch exists to solve a real personal problem: **too much to manage, too little mental bandwidth.**

The creator has a lot on their plate and finds it hard to concentrate or remember everything. Glitch takes over the cognitive load of daily life — calendar, emails, reminders, shopping, messages — so the human can focus on what actually matters.

**Core promise:** Talk to Glitch like a person. It handles the rest.

---

## 👤 Creator Profile

- Full-stack software engineer
- Python backend, React + TypeScript frontend
- Values: clean code, security, scalability, excellent systems
- Location: Trelleborg, Sweden (recently moved)
- Languages: Spanish (primary), Swedish (location)
- WhatsApp number: +46762547179

---

## 🤖 Glitch's Personality

- **Name origin:** "Glitch" = technical error → ironic for a perfect assistant
- **Tagline:** *"They called it a glitch. I call it mine."*
- **Character traits:**
  - Slightly mischievous but deeply loyal
  - Never overly serious
  - Admits when it doesn't know something — with grace, not failure
  - Feels like a companion, not a corporate tool
  - Has a subtle sense of humor
- **Visual aesthetic:** Cyan + magenta + black. Vaporwave/tech-glitch style
- **Mascot:** Animated face with expressive eyes, occasional glitch distortion effect (cute, not scary)
- **Hotword:** "Oye Glitch..." or "Hey Glitch..."
- **Languages:** Spanish, Swedish, English (multilingual)

---

## 🏗️ Architecture

```
WhatsApp (Twilio)  ←→  Python Agent (Railway)  ←→  Phone Calls (Vapi)
                              ↓
┌──────────────────────────────────────────────────┐
│ Claude API (Sonnet) → chat conversation/decisions │
│ Claude API (Haiku)  → voice agent (via Vapi)      │
│ Vapi + Deepgram     → outbound AI phone calls     │
│ Twilio              → WhatsApp messaging           │
│ Google Calendar     → multi-calendar (5 calendars) │
│ OpenWeatherMap      → weather + umbrella alerts     │
│ Notion API          → dashboard (5 databases)       │
│ PostgreSQL          → contacts, reminders, memory   │
│ APScheduler         → cron jobs & scheduled tasks   │
│ Pillow              → daily summary image cards     │
│ ElevenLabs          → TTS voice (future ESP32)      │
│ Whisper STT         → voice transcription           │
└──────────────────────────────────────────────────┘
```

---

## 📱 Device Ecosystem (Multi-client)

One agent brain. Multiple physical bodies. Same memory across all.

| Device | Use Case | Status |
|--------|----------|--------|
| WhatsApp (Twilio sandbox) | Primary interface, everywhere | ✅ Configured |
| ESP32-S3-Touch-AMOLED-1.75C (circular) | Pocket companion, always listening | 🛒 Arriving June 12 |
| ESP32-S3-Touch-LCD-3.5" | Desk device, home office | 📋 Phase 5 |

### Hardware Decision Log
- **Pi Zero** → discarded (too limited RAM)
- **ESP32-C6** → discarded (no audio)
- **ESP32-S3 1.8" AMOLED rectangular** → runner-up
- **ESP32-S3-Touch-AMOLED-1.75C circular** → **CHOSEN** ✅
  - Circular display perfect for mascot face
  - More pocket-friendly
  - Premium gadget aesthetic
  - Better for future commercial product
- **Raspberry Pi in home** → discarded (replaced by ESP32 3.5" desk)

### ESP32 Mascot States
```
💙 Blue pulsing   → listening for hotword
🔵 Blue solid     → recording voice
🟡 Yellow         → processing
🟢 Green          → responding
🔴 Red            → error / no WiFi
⚪ Off            → standby
```

---

## 🔧 Technical Stack

| Layer | Technology | Status | Purpose |
|-------|-----------|--------|---------|
| Backend | Python 3.12 + FastAPI | ✅ | Main API |
| Agent | Anthropic Messages API (tool use) | ✅ | Orchestration — no LangGraph |
| AI Chat | Claude Sonnet 4 | ✅ | WhatsApp conversation & decisions |
| AI Voice | Claude Haiku | ✅ | Vapi voice agent (fast responses) |
| Phone Calls | Vapi + Deepgram nova-3 | ✅ | Outbound AI phone calls |
| Voice Input | OpenAI Whisper | ✅ | STT for WhatsApp voice notes |
| Voice Output | ElevenLabs | ✅ | Natural TTS multilingual |
| Database | PostgreSQL (Railway) | ✅ | Contacts, reminders, conversations |
| Scheduler | APScheduler (CronTrigger) | ✅ | Reminders & daily summary cron |
| Messaging | Twilio WhatsApp | ✅ | Primary channel + scheduled msgs |
| Calendar | Google Calendar API | ✅ | 5 calendars (Google + Outlook ICS) |
| Dashboard | Notion API | ✅ | 5 databases under Glitch Dashboard |
| Weather | OpenWeatherMap | ✅ | Forecast + umbrella alerts |
| Image Gen | Pillow | ✅ | Daily summary dark-theme cards |
| Server | Railway | ✅ | Deploy & hosting |
| Email | Gmail API + Yahoo IMAP | 📋 Phase 2 | Read & send |
| Music | Spotify API | 📋 Phase 3 | Voice control |
| Smart Home | Google Nest/Home API | 📋 Phase 3 | Home control |
| ESP32 Firmware | MicroPython + LVGL | 📋 Phase 4 | Physical devices |
| Hotword | Porcupine (Picovoice) | 📋 Phase 4 | Offline wake word |

---

## 🔐 Credentials & Configuration

> ⚠️ NEVER commit actual values to GitHub. Use Railway environment variables.

```env
# Anthropic
ANTHROPIC_API_KEY=✅ ready

# Twilio
TWILIO_ACCOUNT_SID=✅ stored
TWILIO_AUTH_TOKEN=✅ stored
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
MY_WHATSAPP_NUMBER=whatsapp:+46762547179

# Vapi (AI phone calls)
VAPI_API_KEY=✅ stored
VAPI_ASSISTANT_ID=1701aba3-771c-46f6-a92a-7e16cfdc514d
VAPI_PHONE_NUMBER_ID=2a462aa1-2b30-42b2-afe8-ed36f2f9a2db

# ElevenLabs
ELEVENLABS_API_KEY=✅ ready
ELEVENLABS_VOICE_ID=oSMrjv0Y90fQz1KX393H
ELEVENLABS_MODEL=eleven_multilingual_v2

# Google
GOOGLE_PROJECT_ID=glitch-assistant-497009
GOOGLE_CREDENTIALS_JSON=✅ OAuth desktop app
GOOGLE_TOKEN_JSON=✅ stored in Railway
# OAuth scopes: auth/calendar
# Calendars detected: Gmail primary, Calendario, Familia,
#   Alianne Newton (Outlook ICS, hidden), Festivos en España (hidden)

# Notion
NOTION_API_KEY=✅ stored (internal integration)
# Dashboard page: "Glitch Dashboard" (user-created, integration connected)
# Databases: Agenda, Recordatorios, To-Do, Lista de Compras, Log Glitch

# Weather
OPENWEATHERMAP_API_KEY=✅ stored

# Railway PostgreSQL (auto-provided)
DATABASE_URL=auto_provided_by_railway

# User Config
USER_CITY=Trelleborg
USER_TIMEZONE=Europe/Stockholm
USER_LANGUAGE=es
USER_WHATSAPP=+46762547179
```

---

## ✅ Setup Progress

```
[✅] Anthropic API key — ready
[✅] Railway — deployed and running
     Domain: alluring-courtesy-production-9b65.up.railway.app
[✅] Twilio — sandbox active, webhook connected
     Sandbox number: +14155238886
[✅] Vapi — outbound calls working
     Assistant ID configured, Deepgram nova-3 transcriber
[✅] Google Calendar API — OAuth token stored, 5 calendars detected
[✅] ElevenLabs — voice "Glitch" created
[✅] OpenWeatherMap — API key stored, forecast working
[✅] Notion — internal integration connected
     Glitch Dashboard page with 5 databases
[✅] PostgreSQL — tables: conversations, reminders, contacts
[✅] First WhatsApp message sent and working
[✅] First AI phone call made and working
[✅] Daily summary cron jobs active (L-V 8:00, S-D 10:00)
[ ] GitHub repo — create: glitch-assistant (private)
```

---

## 📅 Implementation Phases

### Phase 1 — Core Agent ✅ COMPLETE
**Goal:** Talk to Glitch via WhatsApp. It understands and responds.

**Deliverables:**
- ✅ Python FastAPI project structure
- ✅ Anthropic Messages API with tool use (replaced LangGraph)
- ✅ Twilio WhatsApp webhook (receive + send messages)
- ✅ Whisper STT — transcribe incoming voice notes
- ✅ ElevenLabs TTS — respond with voice
- ✅ Google Calendar — read + create events (multi-calendar with conflict detection)
- ✅ Reminders with APScheduler (replaced Redis + Celery)
- ✅ PostgreSQL — conversation memory + contacts
- ✅ Deploy on Railway with env vars
- ✅ Daily summary as image card (L-V 8:00, S-D 10:00)
- ✅ Outbound AI phone calls via Vapi
- ✅ Contacts system (save, lookup, auto-resolve by name)
- ✅ WhatsApp messaging to contacts (immediate + scheduled)

**Result:** Send voice/text → Glitch understands → acts → confirms. Can also make AI phone calls.

---

### Phase 2 — Full Productivity (Weekend 2) — PARTIALLY DONE
- ✅ Dynamic shopping list (Notion — add items, clear/archive list)
- ✅ Notion API — full dashboard (5 databases: Agenda, To-Do, Compras, Recordatorios, Log)
- ✅ Scheduled messages with contact resolution
- ✅ To-do list management (add, update status)
- Gmail API — event detection in emails
- Yahoo Mail — IMAP/SMTP
- Smart spam filter with auto-unsubscribe
- Automatic event detection from incoming emails

---

### Phase 3 — Context & Intelligence (Weekend 3) — PARTIALLY DONE
- ✅ OpenWeatherMap — forecast + umbrella alerts (in daily summary)
- WiFi trigger via iOS Shortcuts
- Smart alerts (event at home but you left)
- Spotify API — voice music control
- Google Nest/Home API — smart home
- YouTube Data API — search & links
- Recipe suggestions by ingredients + time
- Do not disturb mode

---

### Phase 4 — Pocket Device (Weekend 4)
**Hardware:** ESP32-S3-Touch-AMOLED-1.75C (arriving June 12)
- MicroPython firmware
- Local hotword detection
- Audio capture + WiFi streaming
- Response playback on ESP32 speaker
- AMOLED mascot animations
- LED RGB feedback

---

### Phase 5 — Multi-device + Desk (Weekend 5-6)
- ESP32-S3-Touch-LCD-3.5" desk device
- Device registry in agent
- Presence context by WiFi SSID
- Unified history across all devices
- Facial recognition on approach (desk device)

---

## 🚀 Future Features Backlog

### 📞 Automatic Phone Calls ✅ IMPLEMENTED
```
"Glitch, llama a María y agenda una cita para el jueves"
→ Vapi calls contact (auto-resolved from saved contacts)
→ Deepgram nova-3 transcribes in real-time
→ Claude Haiku conducts conversation with calendar context
→ Post-call webhook creates event + syncs to Notion
→ Conflict detection prevents double-booking
```
Tech: Vapi + Deepgram + Claude Haiku + Google Calendar
Status: Working in production

### 📧 Appointment Booking via Email (Phase 2)
```
Glitch sends email → monitors Gmail → confirms in Calendar
```
Tech: Gmail API (already planned)
Priority: Phase 2

### 🔍 Professional Verification (Phase 3)
```
Find professionals → analyze reviews → recommend best option
```
Tech: Google Maps API + web search
Priority: Phase 3

### 💰 Control de Gastos ✅ IMPLEMENTED
```
"Gasté 450kr en ICA" → registers expense with auto-categorization
"¿Cuánto gasté este mes?" → summary by category with % bars
"Mis gastos de esta semana" → detailed list with totals
```
Tech: Notion DB (Gastos) + Claude auto-categorization
Status: Working in production

### 📱 Missed Call Response (Android only)
iOS doesn't allow call access from external apps.
Android: Tasker detects missed call → POST to agent → SMS sent

### 🧪 Experimental (Future)
- **Dashboard web** — React mini-app with stats: expenses, exercise, nutrition, memories
- **Automatizaciones condicionales** — "Si mañana llueve, cancela hiking y avísame" (if/then rules)
- **Home Assistant integration** — Smart home control: lights, heating, etc.

---

## 💡 Key Design Decisions

### Communication Channel
- WhatsApp as primary (user uses exclusively)
- Twilio sandbox number as bot contact "Glitch 🤖"
- Personal WhatsApp untouched

### Anti-Spam Philosophy
- Agent NEVER interrupts unless scheduled or urgent
- Three modes: Minimal (1x/day) | Normal | Proactive
- "Do not disturb until 5pm" always available

### Voice Architecture
- WhatsApp voice notes → user speaks TO Glitch
- Twilio Voice calls → Glitch alerts user hands-free
- ESP32 speaker → at home/pocket without phone
- ElevenLabs multilingual v2 → same voice in ES/SV/EN

### AI Model Strategy
```python
# WhatsApp chat → Claude Sonnet (best reasoning + tool use)
# Vapi voice agent → Claude Haiku (fast, low latency for calls)
# No Gemini router — Claude handles everything via Anthropic Messages API
```

### Shopping List Design (via Notion)
- Stored in Notion "Lista de Compras" database
- Categories: Comida, Hogar, Higiene, Otro
- "Clear list" archives items (never hard deletes)
- "Ya hice las compras" → archives all, fresh list ready
- Future: Auto-send when leaving home (WiFi trigger)

### Multi-device Principle
```python
payload = {
    "device": "esp32_pocket|whatsapp|esp32_desk",
    "location_hint": "home|work|away",
    "response_preference": "short_audio|text|long_audio"
}
```

---

## 📁 Project Structure

```
glitch-assistant/
├── GLITCH_CONTEXT.md            ← this file
├── Dockerfile                   ← includes fonts-dejavu-core for Pillow
├── railway.toml
├── requirements.txt             ← Pillow, notion-client, anthropic, etc.
├── google_credentials.json      ← OAuth desktop app (not committed)
├── token.json                   ← OAuth refresh token (not committed)
├── backend/
│   ├── __init__.py
│   ├── main.py                  ← FastAPI app, lifespan, cron jobs, /media endpoint
│   ├── config.py                ← Pydantic settings from env vars
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── brain.py             ← Anthropic Messages API with tool use
│   │   ├── prompts.py           ← system prompt (ES/SV/EN)
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── calendar.py      ← Google Calendar (multi-calendar, conflict detection)
│   │       ├── calls.py         ← Vapi outbound phone calls
│   │       ├── contacts.py      ← contact CRUD (name → phone auto-resolve)
│   │       ├── daily_summary.py ← weather + agenda + verse → image card
│   │       ├── reminders.py     ← APScheduler reminders + send_whatsapp
│   │       └── summary_card.py  ← Pillow dark-theme image generator
│   ├── channels/
│   │   ├── __init__.py
│   │   ├── whatsapp.py          ← Twilio WhatsApp webhook
│   │   └── vapi_webhook.py      ← Vapi post-call webhook (event creation)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── database.py          ← SQLAlchemy engine + session
│   │   ├── notion.py            ← Notion API (5 databases)
│   │   ├── scheduler.py         ← APScheduler setup
│   │   ├── transcription.py     ← Whisper STT
│   │   └── voice.py             ← ElevenLabs TTS
│   └── models/
│       ├── __init__.py
│       ├── contact.py           ← Contact model (name, phone, language)
│       ├── conversation.py      ← Conversation history
│       └── reminder.py          ← Reminder model
└── esp32/                       ← Phase 4 (hardware device)
    └── (pending)
```

---

## 💰 Cost Structure

### One-time Hardware
| Item | Cost |
|------|------|
| ESP32-S3-Touch-AMOLED-1.75C | ~$35 |
| Battery + speaker + case | ~$28 |
| ESP32-S3-Touch-LCD-3.5" (desk) | ~$65 |
| Battery + speaker (desk) | ~$15 |
| **Total** | **~$143** |

### Monthly
| Service | Cost |
|---------|------|
| Railway | $5 |
| Claude API (Sonnet + Haiku) | $8-12 |
| Twilio WhatsApp | $6 |
| ElevenLabs | $5 |
| Vapi (phone calls) | $5-10 (usage-based) |
| Google Calendar API | $0 free |
| Notion | $0 free |
| OpenWeatherMap | $0 free |
| **Total** | **~$29-38/mo** |

---

## 🏢 Commercialization Roadmap

```
NOW        → Build for yourself. Be user #1.
3-6 mo     → Use, refine, perfect daily.
6-12 mo    → Private beta: 10-20 people.
12-18 mo   → Public SaaS launch + Product Hunt.
18-24 mo   → Hardware product + white label B2B.
```

### Competitive Advantage
- Physical device with personality (unique in market)
- Named mascot with backstory (brand, not product)
- End-to-end experience (software + hardware)
- Privacy-first (your data, your server)
- Same price as competitors (~$25/mo) but 2x features

---

## 🚨 Pending Actions

```
1. Create GitHub repo: glitch-assistant (private)
2. Re-save contacts via WhatsApp (DB was reset during development)
3. Gmail API integration (Phase 2)
4. ESP32 hardware setup when device arrives (June 12)
```

---

## 📋 How to Use This Document

When starting a new Claude session (here or Claude Code):

```
"Read GLITCH_CONTEXT.md and let's continue
 building from where we left off.
 Current status: Phase 1 complete, working on Phase 2."
```

Deploy command:
```bash
railway up    # Force deploy from local files
```

Test endpoints:
```
POST /test/daily-summary     # Trigger daily summary manually
GET  /media/{filename}       # Serve generated images
POST /webhook/whatsapp       # Twilio WhatsApp webhook
POST /webhook/vapi           # Vapi post-call webhook
```

---

*Last updated: May 22, 2026*
*Document version: 3.0*
*Status: Phase 1 complete ✅ — Phase 2 in progress (email pending)*

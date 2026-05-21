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
User Voice / WhatsApp
        ↓
Python Agent (Railway — cloud brain)
        ↓
┌─────────────────────────────────────────┐
│ Claude API      → conversation/decisions │
│ Gemini Pro      → Gmail, Calendar, docs  │
│ Google Calendar → work + personal unified│
│ Gmail API       → email read/send        │
│ Yahoo IMAP      → secondary email        │
│ Twilio          → WhatsApp + SMS         │
│ ElevenLabs      → TTS natural voice      │
│ Whisper STT     → voice transcription    │
│ OpenWeatherMap  → real-time weather      │
│ Google Maps API → traffic + routes       │
│ Spotify API     → music control          │
│ Google Nest API → smart home             │
│ YouTube API     → video search           │
│ Notion API      → dashboard              │
│ PostgreSQL      → persistent data        │
│ Redis + Celery  → task queue/schedulers  │
└─────────────────────────────────────────┘
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

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Backend | Python 3.12 + FastAPI | Main API |
| Agent | LangGraph + LangChain | Orchestration |
| AI Primary | Claude API (Sonnet) | Conversation & decisions |
| AI Google | Gemini Pro (already owned) | Gmail, Calendar, long docs |
| Voice Input | OpenAI Whisper | STT (free) |
| Voice Output | ElevenLabs | Natural TTS multilingual |
| Database | PostgreSQL | Persistent data |
| Task Queue | Redis + Celery | Reminders & schedulers |
| Messaging | Twilio WhatsApp + SMS | Primary channel |
| Email | Gmail API + Yahoo IMAP | Read & send |
| Calendar | Google Calendar API | Work + personal |
| Dashboard | Notion API | Visual overview |
| Weather | OpenWeatherMap | Real-time |
| Traffic | Google Maps API | Routes |
| Music | Spotify API | Voice control |
| Smart Home | Google Nest/Home API | Home control |
| Server | Railway | Deploy & hosting |
| ESP32 Firmware | MicroPython + LVGL | Physical devices |
| Hotword | Porcupine (Picovoice) | Offline wake word |

---

## 🔐 Credentials & Configuration

> ⚠️ NEVER commit actual values to GitHub. Use Railway environment variables.

```env
# Anthropic
ANTHROPIC_API_KEY=✅ ready (not shown for security)

# Twilio
TWILIO_ACCOUNT_SID=✅ stored in .env (not shown for security)
TWILIO_AUTH_TOKEN=✅ regenerated and stored in .env
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
MY_WHATSAPP_NUMBER=whatsapp:+46762547179

# ElevenLabs
ELEVENLABS_API_KEY=✅ ready (not shown for security)
ELEVENLABS_VOICE_ID=oSMrjv0Y90fQz1KX393H
ELEVENLABS_MODEL=eleven_multilingual_v2
ELEVENLABS_VOICE_NAME=Glitch (custom created voice)

# Google
GOOGLE_PROJECT_ID=glitch-assistant-497009
GOOGLE_CREDENTIALS_JSON=✅ downloaded as JSON desktop app
GOOGLE_CALENDAR_ID=primary
# OAuth scopes: auth/calendar, gmail.modify, gmail.send, gmail.readonly

# Railway PostgreSQL (auto-provided by Railway)
DATABASE_URL=auto_provided_by_railway

# Redis (auto-provided by Railway)
REDIS_URL=auto_provided_by_railway

# Weather
OPENWEATHERMAP_API_KEY=pending

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
[✅] Railway account — trial active (30 days / $5)
[✅] Twilio account — sandbox active
     Sandbox number: +14155238886
     Code: join tie-valley
     ⚠️  Auth Token needs regeneration
[✅] Google Cloud project — glitch-assistant-497009
[✅] Google Calendar API — enabled
[✅] Gmail API — enabled
[✅] OAuth credentials — desktop app created + JSON downloaded
     Scopes: calendar, gmail.modify, gmail.send, gmail.readonly
[✅] ElevenLabs account — free plan (9,348 credits remaining)
     Voice "Glitch" created with AI voice tool
     Voice ID: oSMrjv0Y90fQz1KX393H
     Model: eleven_multilingual_v2
     API key created with minimal permissions
[ ] GitHub repo — create: glitch-assistant (private)
[ ] Local dev environment setup
[ ] First Railway deploy
[ ] WhatsApp sandbox webhook connected
[ ] First message to Glitch ✅
```

---

## 📅 Implementation Phases

### Phase 1 — Core Agent (Weekend 1) ← START HERE
**Goal:** Talk to Glitch via WhatsApp. It understands and responds.

**Deliverables:**
- Python FastAPI project structure
- LangGraph agent with Claude API
- Twilio WhatsApp webhook (receive + send messages)
- Whisper STT — transcribe incoming voice notes
- ElevenLabs TTS — respond with voice
- Google Calendar — read + create events
- Basic reminders (Redis + Celery)
- PostgreSQL — conversation memory
- Deploy on Railway with env vars
- Daily voice briefing (morning summary)

**Result:** Send voice note → Glitch transcribes → understands → acts → confirms by voice

---

### Phase 2 — Full Productivity (Weekend 2)
- Gmail API — event detection in emails
- Yahoo Mail — IMAP/SMTP
- Smart spam filter with auto-unsubscribe
- Dynamic shopping list (create, clear, history)
- Scheduled messages/emails with approval flow
- Claude/Gemini smart router
- Notion API — full dashboard
- Automatic event detection from incoming emails

---

### Phase 3 — Context & Intelligence (Weekend 3)
- OpenWeatherMap — real-time weather
- Google Maps API — traffic & routes
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

### 📞 Automatic Phone Calls (Phase 4-5)
```
"Glitch, find a dentist in Trelleborg and book next week"
→ Twilio Voice calls clinic
→ ElevenLabs conducts conversation
→ Whisper transcribes response
→ Appointment confirmed + Calendar updated
```
Tech: Twilio Voice + ElevenLabs + Whisper
Priority: Post-launch

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

### 📱 Missed Call Response (Android only)
iOS doesn't allow call access from external apps.
Android: Tasker detects missed call → POST to agent → SMS sent

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

### AI Router Logic
```python
if task in ["gmail", "calendar", "drive", "weather", "long_doc"]:
    use Gemini Pro  # native Google, real-time
else:
    use Claude API  # conversation, reasoning, writing
```

### Shopping List Design
- Persists between sessions
- "Clear list" archives (never hard deletes)
- History always available
- "Repeat last week's list" supported
- Auto-send when leaving home (WiFi trigger)

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
├── README.md
├── GLITCH_CONTEXT.md          ← this file
├── .env.example
├── .gitignore
├── Dockerfile
├── railway.toml
├── requirements.txt
├── backend/
│   ├── main.py                ← FastAPI entry point
│   ├── config.py              ← settings & env vars
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── graph.py           ← LangGraph agent
│   │   ├── prompts.py         ← system prompts
│   │   ├── router.py          ← Claude/Gemini router
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── calendar.py    ← Google Calendar
│   │       ├── gmail.py       ← Gmail read/send
│   │       ├── reminders.py   ← Redis reminders
│   │       ├── shopping.py    ← Shopping list
│   │       └── weather.py     ← OpenWeatherMap
│   ├── channels/
│   │   ├── whatsapp.py        ← Twilio webhook
│   │   └── device.py          ← ESP32 endpoint
│   ├── services/
│   │   ├── voice.py           ← ElevenLabs TTS
│   │   ├── transcription.py   ← Whisper STT
│   │   └── scheduler.py       ← Celery tasks
│   └── models/
│       ├── user.py
│       ├── reminder.py
│       ├── message.py
│       └── shopping_list.py
├── esp32/
│   ├── main.py
│   ├── mascot/
│   │   ├── animations.py
│   │   └── states.py
│   └── audio/
│       ├── capture.py
│       └── playback.py
└── docs/
    ├── ROADMAP.md
    └── FUTURE.md
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
| Claude API | $8-12 |
| Twilio WhatsApp + number | $6 |
| ElevenLabs | $5 |
| Gemini Pro | $0 owned |
| Google APIs | $0 free |
| Notion | $0 free |
| OpenWeatherMap | $0 free |
| **Total** | **~$24-28/mo** |

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

## 🚨 Pending Actions Before First Deploy

```
1. ⚠️  REGENERATE Twilio Auth Token
   (was visible in chat session)

2. Create GitHub repo: glitch-assistant (private)

3. Set up local Python environment

4. Add google_credentials.json to project
   (never commit to git — use Railway env vars)

5. Connect Twilio sandbox webhook to Railway URL
   after first deploy

6. Test first WhatsApp message to Glitch
```

---

## 📋 How to Use This Document

When starting a new Claude session (here or Claude Code):

```
"Read GLITCH_CONTEXT.md and let's continue
 building from where we left off.
 Current status: all APIs configured,
 next step is Phase 1 code implementation."
```

Claude Code command to start:
```bash
claude "Read GLITCH_CONTEXT.md and help me 
build Phase 1 of the Glitch assistant project"
```

---

*Last updated: May 21, 2026*
*Document version: 2.0*
*Status: All APIs configured ✅ — Ready for Phase 1 code*

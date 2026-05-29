# Glitch — Personal AI Assistant

A production-grade conversational AI assistant that lives in WhatsApp and can make real phone calls on your behalf. Built from scratch with a multi-modal architecture: text, voice notes, and AI-driven outbound/inbound telephony — all orchestrated by Claude and grounded by a semantic memory system backed by pgvector.

---

## What Glitch Does

Glitch is a fully autonomous personal assistant. You talk to it via WhatsApp (text or voice note); it understands context, remembers your preferences, and acts. It can also pick up your phone and call anyone — booking appointments, leaving messages — in Swedish, Spanish, or English.

### Capabilities

| Domain | Features |
|--------|----------|
| **Calendar** | Read today's agenda, create/edit/delete events, conflict detection across multiple calendars (Google + Outlook ICS) |
| **Phone calls** | Outbound AI calls via Vapi — books appointments, negotiates times against your real calendar, retries if unanswered |
| **Inbound calls** | Takes messages when you're busy; summarizes and forwards via WhatsApp |
| **Email** | Read, send, reply — Gmail and Yahoo Mail |
| **Reminders** | Scheduled WhatsApp messages at any future time |
| **Contacts** | Save contacts with language preference; auto-resolved on calls and SMS |
| **Notion** | To-dos, shopping list, notes, food diary (with macro tracking), expense log, activity history |
| **Spotify** | Play, pause, skip, volume, queue, recommendations by mood or activity |
| **Web search** | Tavily-powered search with page extraction |
| **Memory** | Semantic long-term memory — remembers your preferences, decisions, and personal facts across sessions |
| **Daily briefing** | Proactive daily summary at 8:00 (weekdays) / 10:00 (weekends) |
| **Event alerts** | Proactive 15-minute pre-event notifications via WhatsApp |
| **Email → Calendar** | Scans inbox every 30 min and auto-detects event invitations |
| **Voice I/O** | Voice notes transcribed via OpenAI Whisper; replies narrated via ElevenLabs TTS |

---

## Architecture

```
WhatsApp (Twilio)
       │
       ▼
FastAPI webhook  ──────────────────────────────────────────────────────┐
       │                                                               │
       ▼                                                               ▼
  brain.py (Agent loop)                                     Vapi webhook
       │                                                     (phone calls)
       │  RAG: embed query → pgvector similarity search             │
       │  → inject top-k memories into system prompt               │
       ▼                                                             │
  Claude Sonnet (tool use loop)  ◄────────────────────────────────────┘
       │
       ├── Google Calendar API
       ├── Gmail / Yahoo IMAP
       ├── Notion API
       ├── Spotify Web API
       ├── Twilio (SMS / WhatsApp)
       ├── Vapi (outbound AI calls)
       ├── ElevenLabs (TTS)
       ├── OpenAI Whisper (STT)
       └── Tavily (web search)

PostgreSQL + pgvector
  ├── memories      (vector embeddings, HNSW index)
  ├── messages      (conversation history)
  ├── reminders     (scheduled jobs)
  └── contacts      (phone book with language preferences)

APScheduler
  ├── daily summary (cron)
  ├── event alerts (every 5 min)
  └── email scan (every 30 min)
```

### Request lifecycle

1. Twilio delivers a WhatsApp message (or voice note) to `/webhook/whatsapp`
2. FastAPI responds immediately (`<Response/>`) and processes in a background task — Twilio never times out
3. If a voice note, Whisper transcribes the audio
4. The agent loop loads conversation history from PostgreSQL (last 50 messages, with old tool results compressed)
5. The current message is embedded (Jina AI v3) and a cosine similarity search against pgvector retrieves the top-k relevant memories — these are injected into the Claude system prompt
6. Claude Sonnet runs a tool-use loop, calling any combination of the 50+ registered tools
7. After the final response, two background threads fire: one saves the exchange as a new memory vector; another uses Claude Haiku to detect whether the exchange contains a preference, decision, or personal fact worth tagging with higher importance
8. The reply is sent back via Twilio (text, or audio + text if the input was a voice note)

---

## Semantic Memory — RAG with pgvector

The memory system is the most technically interesting part of Glitch. Every conversation exchange is embedded and stored so that future sessions can retrieve semantically relevant context — not just keyword matches.

### Schema

```sql
CREATE TABLE memories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(50) NOT NULL,
    content         TEXT NOT NULL,           -- "Usuario: ... \nGlitch: ..."
    embedding       VECTOR(1024) NOT NULL,   -- Jina AI v3 embeddings
    memory_type     VARCHAR(30),             -- conversation | preference | decision | fact | event
    importance      SMALLINT DEFAULT 1,      -- 1-5 scale
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_accessed_at TIMESTAMPTZ DEFAULT now(),
    access_count    INTEGER DEFAULT 0
);
```

### HNSW index

```sql
CREATE INDEX memories_embedding_idx
ON memories USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

HNSW (Hierarchical Navigable Small World) gives sub-millisecond approximate nearest-neighbor search even as the memory store grows to millions of vectors. `m=16` controls the graph connectivity (higher = better recall, more memory); `ef_construction=64` sets the build-time exploration breadth.

### Retrieval query

```sql
SELECT id, content, memory_type, importance,
       1 - (embedding <=> :query_embedding::vector) AS similarity,
       created_at, metadata
FROM memories
WHERE user_id = :user_id
  AND 1 - (embedding <=> :embedding::vector) >= :min_similarity
ORDER BY similarity DESC
LIMIT :limit;
```

The `<=>` operator is pgvector's cosine distance. Subtracting from 1 gives cosine similarity. Results above a configurable threshold are formatted and prepended to the Claude system prompt so the model has relevant history without blowing the context window.

### Automatic importance detection

After every response, a lightweight Claude Haiku call runs in a daemon thread:

```
Analyze this exchange. Respond with JSON:
{"detected": true/false, "type": "preference|decision|fact", "importance": 1-5, "summary": "..."}
```

If `detected=true` and `importance >= 3`, the exchange is re-saved with the elevated importance and tagged type. This creates a two-tier memory: routine conversation (importance 1-2) and high-signal preferences/facts (importance 3-5) — the latter surfaced preferentially in user profile queries.

### Non-blocking saves

All memory writes run in daemon threads so they never add latency to the response path:

```python
threading.Thread(target=save_memory, args=(...), daemon=True).start()
```

---

## AI Phone Calls

Glitch can make real outbound phone calls using a stack of specialized models:

- **Deepgram Nova-3** — real-time speech-to-text, language-specific (`sv`, `es`, `en`)
- **Claude Haiku** — conversational model for the live call (low latency, ~150 tokens per turn)
- **ElevenLabs Turbo v2.5** — neural TTS for natural-sounding speech
- **Vapi** — orchestration layer for the voice pipeline

Before the call, the system injects the user's real calendar busy times into the agent's system prompt so it can negotiate appointment times without double-booking. After the call ends, a separate Claude Sonnet call extracts any agreed appointment from the transcript and creates a Google Calendar event automatically.

Unanswered calls are retried once after 5 minutes via APScheduler. Inbound calls trigger a message-taking agent (British English, warm persona) that summarizes and forwards the message via WhatsApp.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API framework | FastAPI + Uvicorn |
| LLM | Anthropic Claude Sonnet (agent), Claude Haiku (preference detection, voice calls) |
| Embeddings | Jina AI `jina-embeddings-v3` (1024 dimensions) |
| Vector store | PostgreSQL + pgvector + HNSW index |
| ORM | SQLAlchemy 2.0 |
| Scheduler | APScheduler 3.x |
| Messaging | Twilio (WhatsApp + SMS) |
| Voice pipeline | Vapi + Deepgram + ElevenLabs |
| Speech-to-text | OpenAI Whisper |
| Calendar | Google Calendar API (OAuth2) |
| Email | Gmail API + Yahoo IMAP |
| Productivity | Notion API |
| Music | Spotify Web API |
| Web search | Tavily |
| Deployment | Docker + Railway |

---

## Project Structure

```
backend/
├── agent/
│   ├── brain.py          # Agent loop: history, RAG injection, tool dispatch
│   ├── prompts.py        # System prompt
│   └── tools/            # One module per capability domain
│       ├── calendar.py
│       ├── calls.py      # Vapi outbound calls
│       ├── email.py
│       ├── reminders.py
│       ├── spotify.py
│       ├── web_search.py
│       ├── daily_summary.py
│       ├── event_alerts.py
│       └── email_events.py
├── channels/
│   ├── whatsapp.py       # Twilio webhook (text + voice)
│   └── vapi_webhook.py   # Vapi function calls + call lifecycle events
├── models/
│   ├── memory.py         # SQLAlchemy model with Vector(1024) column
│   ├── conversation.py
│   ├── reminder.py
│   └── contact.py
├── services/
│   ├── memory.py         # Embedding generation, similarity search, RAG context builder
│   ├── database.py       # Engine setup, init_db, HNSW index creation
│   ├── scheduler.py      # APScheduler singleton
│   ├── google_auth.py    # OAuth2 for Calendar + Gmail
│   ├── spotify_auth.py   # Spotify PKCE flow
│   ├── notion.py         # All Notion database operations
│   ├── transcription.py  # Whisper STT
│   └── voice.py          # ElevenLabs TTS
├── config.py             # Pydantic settings
└── main.py               # FastAPI app, lifespan, scheduled jobs
```

---

## Setup

```bash
# Clone and install
git clone <repo>
cd glitch_assistant
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Fill in API keys: Anthropic, Twilio, Vapi, Jina, ElevenLabs,
# Google OAuth, Notion, Spotify, Tavily, DATABASE_URL

# Run locally
uvicorn backend.main:app --reload
```

The database tables and pgvector extension are created automatically on first startup via `init_db()`. The HNSW index is built at the same time.

### Required environment variables

```
ANTHROPIC_API_KEY
DATABASE_URL               # PostgreSQL with pgvector extension
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_WHATSAPP_NUMBER
VAPI_API_KEY
VAPI_PHONE_NUMBER_ID
VAPI_ASSISTANT_ID
JINA_API_KEY
ELEVENLABS_API_KEY
OPENAI_API_KEY             # For Whisper STT
NOTION_API_KEY
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
TAVILY_API_KEY
USER_WHATSAPP              # Your WhatsApp number (+countrycode...)
USER_TIMEZONE              # e.g. Europe/Stockholm
```

---

## Design decisions

**Why pgvector + HNSW instead of a dedicated vector database?**
PostgreSQL already handles conversation history, reminders, and contacts. Keeping everything in one database eliminates operational complexity — no Pinecone/Qdrant to manage, no cross-service consistency issues, and the HNSW index gives comparable query latency for a personal assistant's memory scale.

**Why Jina AI v3 at 1024 dimensions instead of OpenAI ada-002 (1536)?**
Jina v3 scores higher on MTEB benchmarks for retrieval tasks, costs less per token, and the smaller dimension reduces storage and index build time with negligible recall loss at this scale.

**Why Claude Haiku for preference detection and voice calls?**
Haiku is fast enough for real-time voice (<300ms generation) and cheap enough to run on every conversation turn for preference detection without making it economically unviable. Sonnet is reserved for the main agent loop where reasoning depth matters.

**Why Vapi instead of building the telephony pipeline directly?**
Vapi handles WebRTC, PSTN bridging, and real-time audio routing. Building that from scratch would be months of infrastructure work with no product benefit. The webhook-based function calling API integrates cleanly with the existing tool dispatch pattern.

**Non-blocking everything**
Memory saves, preference detection, and access-count updates all run in daemon threads. The user gets a response in ~2 seconds; the bookkeeping catches up in the background.

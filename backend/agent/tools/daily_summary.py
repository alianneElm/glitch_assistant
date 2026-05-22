"""Daily morning summary for Glitch.

Sends a WhatsApp message every morning with:
- Today's calendar events
- Pending reminders
- Weather (umbrella alert)
- Traffic to work
- Bible verse
"""

import logging
import random
from datetime import datetime

import httpx

from backend.agent.tools.calendar import get_todays_events
from backend.agent.tools.reminders import list_reminders
from backend.config import settings

logger = logging.getLogger(__name__)


def _get_weather() -> str:
    """Get current weather for Trelleborg. Returns umbrella advisory."""
    if not settings.openweathermap_api_key:
        return ""

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={
                    "q": f"{settings.user_city},SE",
                    "appid": settings.openweathermap_api_key,
                    "units": "metric",
                    "cnt": 8,  # Next 24 hours (3h intervals)
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Check for rain in the next 24h
        rain_periods = []
        temp_min = 100
        temp_max = -100
        for item in data.get("list", []):
            temp = item["main"]["temp"]
            temp_min = min(temp_min, temp)
            temp_max = max(temp_max, temp)
            weather_main = item["weather"][0]["main"].lower()
            if weather_main in ("rain", "drizzle", "thunderstorm"):
                hour = datetime.fromtimestamp(item["dt"]).strftime("%H:%M")
                rain_periods.append(hour)

        temp_str = f"{round(temp_min)}-{round(temp_max)}°C" if temp_min != temp_max else f"{round(temp_min)}°C"

        if rain_periods:
            return f"🌧️ Lleva paraguas — lluvia esperada ({', '.join(rain_periods[:3])}). {temp_str}"
        else:
            return f"☀️ Sin lluvia hoy. {temp_str}"
    except Exception as e:
        logger.exception("Failed to get weather")
        return f"🌤️ No pude consultar el clima: {e}"


def _get_bible_verse() -> str:
    """Get a random Bible verse."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get("https://bible-api.com/?random=verse&translation=reina-valera-1960")
            if resp.status_code == 200:
                data = resp.json()
                ref = data.get("reference", "")
                text = data.get("text", "").strip()
                if text:
                    # Trim to reasonable length
                    if len(text) > 300:
                        text = text[:297] + "..."
                    return f"📖 {ref}\n\"{text}\""
    except Exception:
        logger.exception("Failed to get Bible verse")

    # Fallback: curated list of short verses
    verses = [
        ("Filipenses 4:13", "Todo lo puedo en Cristo que me fortalece."),
        ("Salmos 118:24", "Este es el día que hizo Jehová; nos gozaremos y alegraremos en él."),
        ("Proverbios 3:5-6", "Fíate de Jehová de todo tu corazón, y no te apoyes en tu propia prudencia."),
        ("Isaías 41:10", "No temas, porque yo estoy contigo; no desmayes, porque yo soy tu Dios."),
        ("Jeremías 29:11", "Porque yo sé los pensamientos que tengo acerca de vosotros, dice Jehová, pensamientos de paz, y no de mal."),
        ("Salmos 23:1", "Jehová es mi pastor; nada me faltará."),
        ("Romanos 8:28", "Y sabemos que a los que aman a Dios, todas las cosas les ayudan a bien."),
        ("Mateo 11:28", "Venid a mí todos los que estáis trabajados y cargados, y yo os haré descansar."),
    ]
    ref, text = random.choice(verses)
    return f"📖 {ref}\n\"{text}\""


def build_daily_summary() -> str:
    """Build the complete daily summary message."""
    now = datetime.now()
    day_names_es = {
        "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
        "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
    }
    day_es = day_names_es.get(now.strftime("%A"), now.strftime("%A"))
    date_str = f"{day_es} {now.strftime('%d/%m/%Y')}"
    is_weekend = now.weekday() >= 5

    parts = [f"Buenos días ☀️ {date_str}\n"]

    # Calendar
    events = get_todays_events()
    if "No tienes" in events or "no hay" in events.lower():
        parts.append("📅 Sin eventos hoy — día libre")
    else:
        parts.append(f"📅 {events}")

    # Reminders
    reminders = list_reminders()
    if "No tienes" not in reminders:
        parts.append(f"⏰ {reminders}")

    # Weather
    weather = _get_weather()
    if weather:
        parts.append(weather)

    # Bible verse
    verse = _get_bible_verse()
    if verse:
        parts.append(f"\n{verse}")

    return "\n\n".join(parts)


def send_daily_summary() -> None:
    """Build and send the daily summary via WhatsApp."""
    from twilio.rest import Client

    try:
        summary = build_daily_summary()
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            from_=settings.twilio_whatsapp_number,
            to=settings.my_whatsapp_number,
            body=summary,
        )
        logger.info("Daily summary sent successfully")
    except Exception:
        logger.exception("Failed to send daily summary")

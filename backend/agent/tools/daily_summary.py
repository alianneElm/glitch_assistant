"""Daily morning summary for Glitch.

Sends a WhatsApp image card every morning with:
- Today's calendar events
- Pending reminders
- Weather (temp, UV, wind, rain)
- Recommended outdoor activity
- Bible verse
"""

import logging
import random
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

from backend.agent.tools.calendar import get_todays_events
from backend.agent.tools.reminders import list_todays_reminders
from backend.config import settings

logger = logging.getLogger(__name__)

# Railway public domain for serving media
import os as _os

RAILWAY_DOMAIN = _os.environ.get(
    "RAILWAY_PUBLIC_DOMAIN",
    "alluring-courtesy-production-9b65.up.railway.app",
)

# Trelleborg coordinates for Open-Meteo
_LAT = 55.37
_LON = 13.16


def _get_weather() -> dict:
    """Get detailed weather: temp, wind, UV, rain, conditions.

    Returns a dict with all weather data for the card and activity recommendation.
    """
    result = {
        "temp_min": None, "temp_max": None,
        "wind_avg": 0, "wind_max": 0, "wind_dir": "",
        "uv_max": 0, "uv_label": "",
        "rain": False, "rain_periods": [],
        "conditions": "",
        "summary": "No pude consultar el clima.",
    }

    # --- OpenWeatherMap: temp, rain, wind, conditions ---
    if settings.openweathermap_api_key:
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    "https://api.openweathermap.org/data/2.5/forecast",
                    params={
                        "q": f"{settings.user_city},SE",
                        "appid": settings.openweathermap_api_key,
                        "units": "metric",
                        "cnt": 8,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            temp_min = 100.0
            temp_max = -100.0
            wind_speeds = []
            wind_dirs = []
            conditions_set = set()

            for item in data.get("list", []):
                temp = item["main"]["temp"]
                temp_min = min(temp_min, temp)
                temp_max = max(temp_max, temp)

                wind_speed = item.get("wind", {}).get("speed", 0) * 3.6  # m/s → km/h
                wind_speeds.append(wind_speed)
                wind_dirs.append(item.get("wind", {}).get("deg", 0))

                weather_main = item["weather"][0]["main"].lower()
                weather_desc = item["weather"][0].get("description", "")
                conditions_set.add(weather_desc)

                if weather_main in ("rain", "drizzle", "thunderstorm"):
                    hour = datetime.fromtimestamp(
                        item["dt"], tz=ZoneInfo(settings.user_timezone)
                    ).strftime("%H:%M")
                    result["rain_periods"].append(hour)

            result["temp_min"] = round(temp_min)
            result["temp_max"] = round(temp_max)
            result["wind_avg"] = round(sum(wind_speeds) / len(wind_speeds)) if wind_speeds else 0
            result["wind_max"] = round(max(wind_speeds)) if wind_speeds else 0
            result["rain"] = len(result["rain_periods"]) > 0
            result["conditions"] = ", ".join(list(conditions_set)[:2])

            # Wind direction from average
            if wind_dirs:
                avg_deg = sum(wind_dirs) / len(wind_dirs)
                directions = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
                idx = round(avg_deg / 45) % 8
                result["wind_dir"] = directions[idx]

        except Exception:
            logger.exception("Failed to get OpenWeatherMap data")

    # --- Open-Meteo: UV index (free, no key needed) ---
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": _LAT,
                    "longitude": _LON,
                    "daily": "uv_index_max",
                    "timezone": settings.user_timezone,
                    "forecast_days": 1,
                },
            )
            resp.raise_for_status()
            uv_data = resp.json()

        uv_max = uv_data.get("daily", {}).get("uv_index_max", [0])[0] or 0
        result["uv_max"] = round(uv_max, 1)

        if uv_max <= 2:
            result["uv_label"] = "Bajo"
        elif uv_max <= 5:
            result["uv_label"] = "Moderado"
        elif uv_max <= 7:
            result["uv_label"] = "Alto"
        elif uv_max <= 10:
            result["uv_label"] = "Muy alto"
        else:
            result["uv_label"] = "Extremo"

    except Exception:
        logger.exception("Failed to get UV data from Open-Meteo")

    # Build summary string
    parts = []
    if result["temp_min"] is not None:
        if result["temp_min"] != result["temp_max"]:
            parts.append(f"{result['temp_min']}-{result['temp_max']}°C")
        else:
            parts.append(f"{result['temp_min']}°C")

    if result["uv_max"]:
        parts.append(f"UV {result['uv_max']} ({result['uv_label']})")

    if result["wind_avg"]:
        parts.append(f"Viento {result['wind_avg']} km/h {result['wind_dir']}")
        if result["wind_max"] > result["wind_avg"] + 10:
            parts.append(f"(ráfagas {result['wind_max']})")

    if result["rain"]:
        parts.append(f"Lluvia: {', '.join(result['rain_periods'][:3])}")
    else:
        parts.append("Sin lluvia")

    result["summary"] = " · ".join(parts)
    return result


def _recommend_activity(weather: dict) -> tuple:
    """Recommend best outdoor activity based on weather.

    Returns (activity_name, emoji, reason).
    User likes: hiking, playa, gym, pasear, car camping.
    """
    temp_max = weather.get("temp_max") or 15
    temp_min = weather.get("temp_min") or 10
    wind = weather.get("wind_avg", 0)
    wind_max = weather.get("wind_max", 0)
    uv = weather.get("uv_max", 0)
    rain = weather.get("rain", False)
    is_weekend = datetime.now(ZoneInfo(settings.user_timezone)).weekday() >= 5

    # Bad weather → gym
    if rain or temp_max < 5 or wind_max > 50:
        reason = "Lluvia" if rain else ("Mucho frío" if temp_max < 5 else "Viento fuerte")
        return ("Gym", "🏋️", f"{reason} — mejor entrenar bajo techo")

    # Beach conditions: sunny, warm, low wind
    if temp_max >= 20 and wind < 25 and uv >= 3 and not rain:
        uv_tip = " (usa protector solar)" if uv >= 6 else ""
        return ("Playa", "🏖️", f"{temp_max}°C, viento suave{uv_tip}")

    # Car camping: good weather + weekend
    if is_weekend and temp_min >= 8 and wind < 35 and not rain:
        return ("Car Camping", "🚗⛺", f"Fin de semana con buen clima, {temp_min}-{temp_max}°C")

    # Hiking: mild-warm, manageable wind, no rain
    if 8 <= temp_max <= 30 and wind < 35 and not rain:
        uv_tip = " — protector solar recomendado" if uv >= 6 else ""
        return ("Hiking", "🥾", f"Buen día para la montaña, {temp_max}°C{uv_tip}")

    # Walking: light conditions
    if temp_max >= 5 and wind < 40 and not rain:
        return ("Pasear", "🚶", f"Agradable para caminar, {temp_max}°C")

    # Fallback
    return ("Gym", "🏋️", "El clima no acompaña — entrena duro bajo techo")


def _get_bible_verse() -> tuple[str, str]:
    """Get a random Bible verse in Spanish (Reina Valera). Returns (ref, text)."""
    verses = [
        ("Filipenses 4:13", "Todo lo puedo en Cristo que me fortalece."),
        ("Salmos 118:24", "Este es el día que hizo Jehová; nos gozaremos y alegraremos en él."),
        ("Proverbios 3:5-6", "Fíate de Jehová de todo tu corazón, y no te apoyes en tu propia prudencia."),
        ("Isaías 41:10", "No temas, porque yo estoy contigo; no desmayes, porque yo soy tu Dios."),
        ("Jeremías 29:11", "Porque yo sé los pensamientos que tengo acerca de vosotros, dice Jehová, pensamientos de paz, y no de mal."),
        ("Salmos 23:1", "Jehová es mi pastor; nada me faltará."),
        ("Romanos 8:28", "Y sabemos que a los que aman a Dios, todas las cosas les ayudan a bien."),
        ("Mateo 11:28", "Venid a mí todos los que estáis trabajados y cargados, y yo os haré descansar."),
        ("Josué 1:9", "Mira que te mando que te esfuerces y seas valiente; no temas ni desmayes, porque Jehová tu Dios estará contigo."),
        ("Salmos 46:10", "Estad quietos, y conoced que yo soy Dios."),
        ("Proverbios 16:3", "Encomienda a Jehová tus obras, y tus pensamientos serán afirmados."),
        ("Isaías 40:31", "Los que esperan a Jehová tendrán nuevas fuerzas; levantarán alas como las águilas."),
        ("Salmos 37:5", "Encomienda a Jehová tu camino, y confía en él; y él hará."),
        ("Mateo 6:34", "No os afáneis por el día de mañana, porque el día de mañana traerá su afán."),
        ("Romanos 15:13", "Y el Dios de esperanza os llene de todo gozo y paz en el creer."),
        ("Salmos 91:1", "El que habita al abrigo del Altísimo morará bajo la sombra del Omnipotente."),
        ("2 Timoteo 1:7", "Porque no nos ha dado Dios espíritu de cobardía, sino de poder, de amor y de dominio propio."),
        ("Salmos 139:14", "Te alabaré; porque formidables, maravillosas son tus obras; estoy maravillado, y mi alma lo sabe muy bien."),
        ("Lamentaciones 3:22-23", "Las misericordias de Jehová nunca decaen; nuevas son cada mañana; grande es tu fidelidad."),
        ("Filipenses 4:6-7", "Por nada estéis afanosos, sino sean conocidas vuestras peticiones delante de Dios en toda oración."),
        ("Hebreos 11:1", "Es, pues, la fe la certeza de lo que se espera, la convicción de lo que no se ve."),
    ]
    return random.choice(verses)


def send_daily_summary() -> None:
    """Generate summary card image and send via WhatsApp."""
    from twilio.rest import Client

    from backend.agent.tools.summary_card import generate_summary_card

    try:
        now = datetime.now(ZoneInfo(settings.user_timezone))
        day_names_es = [
            "Lunes", "Martes", "Miércoles", "Jueves",
            "Viernes", "Sábado", "Domingo",
        ]
        month_names_es = {
            1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
            7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
        }
        day_es = day_names_es[now.weekday()]
        date_str = f"{day_es} {now.day} de {month_names_es[now.month]}"

        # Gather data
        events = get_todays_events()
        reminders = list_todays_reminders()
        weather = _get_weather()
        activity_name, activity_emoji, activity_reason = _recommend_activity(weather)
        verse_ref, verse_text = _get_bible_verse()

        # Generate card image
        filename = generate_summary_card(
            date_str=date_str,
            events_text=events,
            reminders_text=reminders,
            weather_text=weather.get("summary", ""),
            verse_ref=verse_ref,
            verse_text=verse_text,
            uv_index=weather.get("uv_max", 0),
            uv_label=weather.get("uv_label", ""),
            wind_avg=weather.get("wind_avg", 0),
            wind_max=weather.get("wind_max", 0),
            wind_dir=weather.get("wind_dir", ""),
            activity_name=activity_name,
            activity_emoji=activity_emoji,
            activity_reason=activity_reason,
        )

        # Send as WhatsApp image
        image_url = f"https://{RAILWAY_DOMAIN}/media/{filename}"
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            from_=settings.twilio_whatsapp_number,
            to=settings.my_whatsapp_number,
            media_url=[image_url],
        )
        logger.info("Daily summary card sent: %s", image_url)

    except Exception:
        logger.exception("Failed to send daily summary card")

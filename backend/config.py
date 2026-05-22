from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# In dev, load .env with override so it wins over empty shell vars.
# In production (Railway), this is a no-op since the file won't exist.
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH, override=True)


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = "whatsapp:+14155238886"
    my_whatsapp_number: str = "whatsapp:+46762547179"

    openai_api_key: str = ""
    groq_api_key: str = ""

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "oSMrjv0Y90fQz1KX393H"
    elevenlabs_model: str = "eleven_multilingual_v2"

    google_token_json: str = ""

    vapi_api_key: str = ""
    vapi_assistant_id: str = ""
    vapi_phone_number_id: str = ""

    database_url: str = ""
    redis_url: str = ""

    user_city: str = "Trelleborg"
    user_timezone: str = "Europe/Stockholm"
    user_language: str = "es"
    user_whatsapp: str = "+46762547179"

    port: int = 8000
    environment: str = "development"

    model_config = {
        "env_file": str(_ENV_PATH) if _ENV_PATH.exists() else None,
        "env_file_encoding": "utf-8",
    }


settings = Settings()

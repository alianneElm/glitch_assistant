import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# Load .env with override=True so it takes priority over empty shell vars
load_dotenv(_ENV_PATH, override=True)


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = "whatsapp:+14155238886"
    my_whatsapp_number: str = "whatsapp:+46762547179"

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "oSMrjv0Y90fQz1KX393H"
    elevenlabs_model: str = "eleven_multilingual_v2"

    database_url: str = ""
    redis_url: str = ""

    user_city: str = "Trelleborg"
    user_timezone: str = "Europe/Stockholm"
    user_language: str = "es"
    user_whatsapp: str = "+46762547179"

    port: int = 8000
    environment: str = "development"

    model_config = {"env_file": str(_ENV_PATH), "env_file_encoding": "utf-8"}


settings = Settings()

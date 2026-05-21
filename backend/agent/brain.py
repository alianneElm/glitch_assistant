from anthropic import Anthropic

from backend.agent.prompts import GLITCH_SYSTEM_PROMPT
from backend.config import settings

client = Anthropic(api_key=settings.anthropic_api_key)

_conversations: dict[str, list[dict]] = {}

MAX_HISTORY = 20


def get_response(user_id: str, message: str) -> str:
    history = _conversations.setdefault(user_id, [])

    history.append({"role": "user", "content": message})

    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=GLITCH_SYSTEM_PROMPT,
        messages=history,
    )

    assistant_text = response.content[0].text
    history.append({"role": "assistant", "content": assistant_text})

    return assistant_text

"""Text-to-speech for the conversational examiner, backed by OpenAI.

The Speaking dialogue agent needs to *speak* its prompts and follow-ups; this
turns an examiner utterance (French text) into audio bytes the client can play.
Kept thin and provider-specific, mirroring :mod:`app.transcription`: the key is
read from ``settings``, the client is built lazily and reused, a missing key
raises ``RuntimeError`` (router → 503), and ``openai.APIError`` propagates
(router → 502).
"""

from openai import AsyncOpenAI

from app.config import settings

# gpt-4o-mini-tts is OpenAI's low-latency speech model; "alloy" is a neutral
# voice that reads French fine (the voice is language-agnostic — the input text
# is French). MP3 keeps the payload small for base64-over-JSON transport.
MODEL = "gpt-4o-mini-tts"
DEFAULT_VOICE = "alloy"
RESPONSE_FORMAT = "mp3"
AUDIO_MIME = "audio/mpeg"

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Lazily build the OpenAI client; raise if no key is configured."""
    global _client
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is not set")
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def synthesize(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """Synthesize French speech for ``text`` and return MP3 bytes."""
    response = await _get_client().audio.speech.create(
        model=MODEL,
        voice=voice,
        input=text,
        response_format=RESPONSE_FORMAT,
    )
    return response.content

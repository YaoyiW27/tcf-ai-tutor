"""Speech-to-text for the Speaking path, backed by OpenAI Whisper.

The Speaking flow stores the *transcript* of a spoken answer in
``answers.content`` and grades that text with the LangGraph speaking grader —
so the only job here is audio bytes → French transcript. Kept deliberately
thin and provider-specific: no persistence, no grading, no graph wiring.

Mirrors :mod:`app.grader`'s client handling: the key is read from ``settings``
(pydantic-settings loads ``.env`` into that object, not ``os.environ``), the
client is built lazily and reused, and a missing key raises ``RuntimeError`` so
the router can turn it into a 503. Provider errors (``openai.APIError``) are
left to propagate for the router to map to a 502.
"""

from openai import AsyncOpenAI

from app.config import settings

# whisper-1 is OpenAI's hosted Whisper endpoint. Language is pinned to French:
# TCF answers are always in French, and pinning avoids Whisper mis-detecting the
# language on short or heavily accented clips.
MODEL = "whisper-1"
LANGUAGE = "fr"

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Lazily build the OpenAI client; raise if no key is configured."""
    global _client
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is not set")
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def transcribe(audio: bytes, filename: str) -> str:
    """Transcribe French speech to text.

    ``audio`` is the raw uploaded bytes and ``filename`` carries the extension
    (e.g. ``recording.webm``) that Whisper uses to detect the container/codec.
    Returns the plain transcript text.
    """
    response = await _get_client().audio.transcriptions.create(
        model=MODEL,
        file=(filename, audio),
        language=LANGUAGE,
    )
    return response.text

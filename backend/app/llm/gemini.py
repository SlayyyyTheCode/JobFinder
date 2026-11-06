import time

from pydantic import ValidationError

from .base import LLMConfigError, LLMError, T


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, fast_model: str, embed_model: str):
        if not api_key:
            raise LLMConfigError("GEMINI_API_KEY is not set. Add it to .env and restart (see README).")
        from google import genai
        self._genai = genai
        self.client = genai.Client(api_key=api_key)
        self.model, self.fast_model, self.embed_model = model, fast_model, embed_model

    def model_name(self, fast: bool = False) -> str:
        return self.fast_model if fast else self.model

    def _call(self, fn, retries: int = 3):
        delay = 2.0
        for attempt in range(retries):
            try:
                return fn()
            except Exception as e:  # SDK raises various transport/API errors
                msg = str(e)
                transient = any(k in msg for k in ("429", "500", "503", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "timeout"))
                if not transient or attempt == retries - 1:
                    raise LLMError(f"Gemini call failed: {msg[:500]}") from e
                time.sleep(delay)
                delay *= 2

    def _contents(self, prompt: str, files):
        from google.genai import types
        parts = [types.Part.from_bytes(data=b, mime_type=m) for b, m in (files or [])]
        parts.append(types.Part.from_text(text=prompt))
        return [types.Content(role="user", parts=parts)]

    def generate_structured(self, prompt, schema: type[T], *, system="", fast=False, files=None,
                            temperature=0.2) -> T:
        from google.genai import types
        cfg = types.GenerateContentConfig(
            system_instruction=system or None,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=schema,
        )
        last_err = None
        for _ in range(2):  # one repair retry on schema violation
            resp = self._call(lambda: self.client.models.generate_content(
                model=self.model_name(fast), contents=self._contents(prompt, files), config=cfg))
            try:
                return schema.model_validate_json(resp.text or "")
            except ValidationError as e:
                last_err = e
        raise LLMError(f"Model output failed schema validation: {last_err}")

    def generate_text(self, prompt, *, system="", fast=False, temperature=0.4) -> str:
        from google.genai import types
        cfg = types.GenerateContentConfig(system_instruction=system or None, temperature=temperature)
        resp = self._call(lambda: self.client.models.generate_content(
            model=self.model_name(fast), contents=self._contents(prompt, None), config=cfg))
        return (resp.text or "").strip()

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 50):
            batch = texts[i:i + 50]
            resp = self._call(lambda: self.client.models.embed_content(model=self.embed_model, contents=batch))
            out.extend(list(e.values) for e in resp.embeddings)
        return out

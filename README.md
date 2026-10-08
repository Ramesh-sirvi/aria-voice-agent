# Aria: AI Voice Support Agent for Aura Skincare

Browser voice agent: speak, Aria answers using brand policy and live order lookup, then you get a transcript and JSON summary.

## Architecture
Browser mic -> Web Speech API (STT, streaming) -> FastAPI `/api/chat` -> LLM with tool calling (`get_order_details`) -> reply text, split into sentences -> `/api/tts` (Sarvam neural Indian voice, clips fetched in parallel so playback starts after the first sentence) -> browser speechSynthesis as automatic fallback.
- **Tool use:** the LLM decides when to call `get_order_details`. Eligibility (`cancellable`, `return_window_open`, `shipping_fee`) is computed in Python, so policy facts never depend on the model's guess.
- **Guardrails:** policy text and rules in the system prompt, plus code-computed eligibility fields from the tool.
- **Barge-in:** if the customer speaks while Aria is talking, TTS is cancelled.
- **Summary:** a second LLM call turns the transcript into JSON (intent, order_id, status, summary).

## Run locally
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # add your key
    uvicorn main:app --reload
Open http://localhost:8000 in Chrome.

## Deploy (Render)
Build: `pip install -r requirements.txt`. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`. Add the env vars. HTTPS is required for the mic and Render provides it.


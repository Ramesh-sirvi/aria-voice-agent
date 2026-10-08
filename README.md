# Aria: AI Voice Support Agent for Aura Skincare

A browser-based voice customer support agent. Click **Start Call**, speak naturally, and Aria (a friendly Indian-English support specialist) answers using Aura Skincare's brand policies and a live order lookup. When the call ends you get a transcript and a structured JSON summary.

**Live app:** https://aria-voice-agent-9htc.onrender.com  |  **Demo video:** https://youtu.be/dP1hVSyJ95Q

## Features
- Natural voice conversation with a live state badge (Listening / Thinking / Speaking) and a "Hearing" line showing what the browser recognised
- Order tools: `get_order_details` (status, courier, eligibility) and `cancel_order` (asks for confirmation first)
- Brand guardrails: refuses out-of-policy returns and cancellations, declines out-of-scope requests, and says so honestly when it lacks information
- Graceful handling of unknown, missing, or mis-heard order IDs ("one zero one", "1 0 1", "ord 101" all resolve to ORD-101)
- Hinglish-friendly replies, optional barge-in (tick the box and use headphones)
- Post-call transcript and JSON summary

## Test orders (also shown on the page)
| ID | Product | Status | Notes |
|---|---|---|---|
| ORD-101 | Vitamin C Serum (30ml), Rs 699 | Out for Delivery | BlueDart BD-982103, expected by 6 PM today |
| ORD-102 | Hydrating Sunscreen SPF 50, Rs 499 | Delivered | Delhivery DL-441029, delivered 14 days ago |
| ORD-103 | Green Tea Face Wash + Toner, Rs 850 | Processing | Ordered 3 hours ago, cancellable |

Try: "Where is order 101?", "Cancel 103" then "yes", "Return order 102", "Book me a flight to Goa", or an unknown ID.

## Architecture
```
Browser mic -> Web Speech API (STT)
            -> FastAPI /api/chat -> LLM (tool calling: get_order_details, cancel_order)
            -> reply text, split into sentences
            -> /api/tts (Sarvam neural Indian voice; clips fetched in parallel)
            -> browser speechSynthesis (automatic fallback)
End of call -> /api/summary -> transcript + JSON
```
- **Stack:** Python + FastAPI backend, a single static HTML page, any OpenAI-compatible LLM (Groq `openai/gpt-oss-120b` with `openai/gpt-oss-20b` as fallback), Sarvam TTS.
- **Tool use:** the LLM decides when to call a tool from the tool descriptions. Order data is never answered from the model's memory.
- **Guardrails, in layers:**
  1. System prompt: persona, policies, rules, and short example replies.
  2. Code: eligibility (`cancellable`, `return_window_open`, `shipping_fee`, `cod_eligible`) is computed in Python, so policy facts do not depend on the model's judgement.
  3. Code: `tidy()` trims runaway replies (max 3 sentences, stops at the first question, removes self-written "User ..." lines).
  4. Cancellation is a real tool that only runs after the customer confirms, and state is kept per call, so testers never affect each other.
- **Echo handling:** speech that mostly matches Aria's own last sentence is ignored while she is speaking.
- **Model fallback:** if a model hits its quota or is unavailable, the next one in `LLM_FALLBACK_MODELS` is tried.

## Run locally
```
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then add your keys
uvicorn main:app --reload
```
Open http://localhost:8000 in **Chrome or Edge** and allow the microphone. Use headphones to avoid echo.

## Environment variables
| Variable | Purpose |
|---|---|
| `LLM_API_KEY` | API key for the LLM provider (required) |
| `LLM_BASE_URL` | OpenAI-compatible endpoint, e.g. `https://api.groq.com/openai/v1` (required) |
| `LLM_MODEL` | Main model ID (required) |
| `LLM_FALLBACK_MODELS` | Comma-separated backup models (optional) |
| `SARVAM_API_KEY` | Enables the Indian neural voice; without it the browser voice is used (optional) |
| `TTS_SPEAKER`, `TTS_MODEL` | Sarvam voice settings, default `priya` / `bulbul:v3` (optional) |

## Deploy (Render)
Build: `pip install -r requirements.txt`. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`. Add the environment variables above. Render provides HTTPS, which the microphone requires. The free tier sleeps when idle, so the first load can take about a minute.

## Known limitations
- Speech recognition uses the browser's Web Speech API (Chrome/Edge), which can mishear in noisy rooms.
- The LLM reply is not streamed, so there is a short pause before Aria speaks.
- Order data is a mock in-memory database, and there is no identity verification.

## Tell us how you think

**1. Why this architecture and stack?**
My browser turns my voice into text, my Python server sends it to the AI model, and a voice service speaks the answer. I chose this so I could control every step, and the rules, like which orders can be cancelled, are checked in my own code. It also used free tools, so it cost nothing.

**2. Most difficult part and how I solved it**
The hardest part was making Aria give correct answers. In testing she claimed to cancel an order when she couldn't, made up facts about the products, and sometimes heard her own voice. I fixed this with a real cancel function that asks for confirmation, policy checks in my code, clearer instructions, and by making the app ignore her own voice.

**3. One more week: what first?**
I would improve the speech recognition first, because it sometimes mishears words, especially with Indian accents. Then I'd make her start speaking sooner, add automatic tests for the rules, and add better Hinglish support.

**4. At 1,000 conversations a day**
I would stop using free plans, keep a backup AI model, and connect a real order database with customer verification like an OTP. I would also save conversations with personal details hidden, track cost and speed, and pass the call to a human when Aria isn't sure.

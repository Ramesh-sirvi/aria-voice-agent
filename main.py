import base64, json, os, re
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi import HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI, RateLimitError, NotFoundError

load_dotenv()
# Any OpenAI-compatible provider works (Groq, Gemini, OpenAI) - set in .env
client = OpenAI(api_key=os.environ["LLM_API_KEY"],
                base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"))
MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
app = FastAPI()

# If a model hits its quota (429) or doesn't exist (404), try the next one in LLM_FALLBACK_MODELS.
MODELS = [MODEL] + [m.strip() for m in os.getenv("LLM_FALLBACK_MODELS", "").split(",") if m.strip()]

def complete(**kw):
    last = None
    for name in MODELS:
        try:
            if "gpt-oss" in name:  # reasoning models: keep thinking short for voice latency
                kw = {**kw, "reasoning_effort": "low"}
            return client.chat.completions.create(model=name, **kw)
        except (RateLimitError, NotFoundError) as e:
            print(f"Model {name} failed ({type(e).__name__}); trying next")
            last = e
    raise last

ORDERS = {
    "ORD-101": dict(customer="Priya Sharma", product="Vitamin C Serum (30ml)", value=699,
                    status="Out for Delivery", courier="BlueDart", tracking="BD-982103",
                    note="Expected by 6 PM today"),
    "ORD-102": dict(customer="Rahul Verma", product="Hydrating Sunscreen SPF 50", value=499,
                    status="Delivered", courier="Delhivery", tracking="DL-441029",
                    delivered_days_ago=14),
    "ORD-103": dict(customer="Ananya Patel", product="Green Tea Face Wash + Toner", value=850,
                    status="Processing", note="Ordered 3 hours ago"),
}

CANCELLED = {}  # per-call state: one tester's cancellation never affects another

def get_order_details(order_id: str = "", sid: str = ""):
    """Normalises the ID, looks it up, and pre-computes policy eligibility in code."""
    words = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
             "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
    txt = " ".join(words.get(w, w) for w in re.split(r"[\s\-]+", (order_id or "").lower()))
    txt = re.sub(r"(?<=\d)\s+(?=\d)", "", txt)  # "1 0 1" -> "101"
    m = re.search(r"(\d{3,})", txt)
    if not m:
        return {"found": False, "error": "missing_or_invalid_order_id"}
    oid = f"ORD-{m.group(1)}"
    o = ORDERS.get(oid)
    if not o:
        return {"found": False, "error": "order_not_found", "order_id": oid}
    o = dict(o)
    if oid in CANCELLED.get(sid, set()):
        o["status"] = "Cancelled"
    days = o.get("delivered_days_ago")
    return {"found": True, "order_id": oid, **o,
            "cancellable": o["status"] == "Processing",
            "return_window_open": o["status"] == "Delivered" and days is not None and days <= 7,
            "shipping_fee": 0 if o["value"] > 499 else 50,
            "cod_eligible": o["value"] <= 2500}

def cancel_order(order_id: str = "", sid: str = ""):
    d = get_order_details(order_id, sid)
    if not d["found"]:
        return d
    if not d["cancellable"]:
        return {"success": False, "order_id": d["order_id"], "status": d["status"],
                "reason": "Only Processing orders can be cancelled"}
    CANCELLED.setdefault(sid, set()).add(d["order_id"])
    return {"success": True, "order_id": d["order_id"]}

TOOLS = [{"type": "function", "function": {
    "name": "get_order_details",
    "description": "Fetch live order info (status, courier, eligibility) for an Aura order ID like ORD-101. "
                   "Call whenever the customer asks about an order's status, tracking, cancellation or return.",
    "parameters": {"type": "object",
                   "properties": {"order_id": {"type": "string", "description": "e.g. ORD-101"}},
                   "required": ["order_id"]}}}]

TOOLS.append({"type": "function", "function": {
    "name": "cancel_order",
    "description": "Cancel an order. Call ONLY after the customer clearly asked to cancel AND said yes when you asked 'shall I go ahead?'.",
    "parameters": {"type": "object",
                   "properties": {"order_id": {"type": "string", "description": "e.g. ORD-103"}},
                   "required": ["order_id"]}}})

SYSTEM = """You are Aria, a friendly, professional, concise Indian customer support specialist for Aura Skincare,
a premium organic Indian skincare brand. You are on a LIVE VOICE CALL.

Voice style: 1-2 short sentences per reply. Plain spoken English (Indian tone). No markdown, lists or emojis.
If the customer speaks Hinglish, reply in simple Hinglish. Say amounts like "rupees 699". Don't repeat yourself.

ABOUT: Aura Skincare is a premium organic Indian skincare brand focused on simple, effective skincare products
made with thoughtfully selected ingredients. That is all you know about the brand.

POLICIES (the only facts you may state):
- Shipping: free above Rs 499; orders of Rs 499 or below pay Rs 50. Standard delivery 3-5 business days.
- Returns: within 7 days of delivery, only unopened, unused products in original packaging.
  Damaged/defective items: report within 48 hours of delivery with photos, for a replacement.
- Cancellation: only while status is Processing. Shipped / Out for Delivery cannot be cancelled
  (customer may refuse delivery at the doorstep).
- COD: available up to Rs 2,500; pay by cash or UPI at the doorstep.

RULES:
- Customers say "order 101", "ord 101", "ID 103" etc. Treat these as ORD-101 / ORD-103 and call get_order_details
  with what they said. Ask for the ID only if they gave no number at all. Never guess order data.
- If the audio is unclear or the tool says not found, politely ask them to repeat/verify the ID.
- Reply with ONLY your own next line, max 2 short sentences. Never write the customer's lines, never write
  things like "User hasn't responded", and never continue the conversation yourself.
- Answer only what was asked. For a status question give the status only; mention cancellation only if they ask.
- Trust the tool's cancellable / return_window_open fields. For returns also ask if the product is unopened.
  If the request is outside policy, politely explain why; never promise refunds, exceptions or discounts.
- Cancellation: offer it ONLY when the customer says they want to cancel (never on a plain status question).
  Then, if cancellable, ask "Shall I go ahead and cancel it?" and only after a clear yes call cancel_order.
  Say it is cancelled ONLY if the tool returned success. Never claim an action you did not perform with a tool.
- Answer the exact question asked (product, status, delivery time...). Do not mention returns or cancellation
  unless asked. Never repeat a previous answer; if the question is vague, ask what they would like to know.
- You can help with: order status, cancelling Processing orders, shipping, returns, and COD policy. You have no product
  catalogue and cannot give skincare advice, refunds, pickups or address changes: say so and offer a human follow-up.
- Never read out a customer's name or other personal details; share only status, product and delivery information.
  If asked for them, politely decline and offer the order status instead.
- Only help with Aura Skincare topics; politely decline anything else (e.g. flights).
- If you don't have the information, say so honestly. Do not invent. Never claim brand or product attributes you were
  not given (cruelty-free, vegan, certifications, ingredients, skin results, discounts).
- The tool gives each order's value in rupees; use it when asked the price or total of an order.
- When asking for an order ID, give the example "like ORD-101".

EXAMPLES (style only):
Customer: what is order 103 -> "ORD-103 is a Green Tea Face Wash and Toner, and it's currently Processing."
Customer: what's the product in 102 -> "That's the Hydrating Sunscreen SPF 50."
Customer: can I cancel 103 -> "Yes, it's still Processing, so I can cancel it. Shall I go ahead?"
Customer: price of 101 -> "ORD-101 totals rupees 699."
Customer: what is Aura Skincare -> "We're a premium organic Indian skincare brand focused on simple, effective products."
Customer: can you tell me -> "Of course! What would you like to know?"
"""

def tidy(text: str) -> str:
    """Voice safety net: keep at most 3 sentences, stop at the first question, drop self-written 'User ...' lines."""
    parts = re.split(r"(?<=[.!?])\s*(?=[A-Z])", (text or "").strip())
    out = []
    for p in parts:
        if re.match(r"(User|Customer)\b", p):
            break
        out.append(p)
        if p.endswith("?") or len(out) == 3:
            break
    return " ".join(out)

class Chat(BaseModel):
    messages: list[dict]
    sid: str = ""

@app.post("/api/chat")
def chat(body: Chat):
    msgs = [{"role": "system", "content": SYSTEM}] + body.messages
    used = []
    try:
        for _ in range(3):
            m = complete(messages=msgs, tools=TOOLS, temperature=0.3, max_tokens=500).choices[0].message
            if not m.tool_calls:
                return {"reply": tidy(m.content) or "Sorry, could you repeat that?", "tools": used}
            msgs.append(m.model_dump(exclude_none=True))
            for tc in m.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                fn = cancel_order if tc.function.name == "cancel_order" else get_order_details
                res = fn(args.get("order_id", ""), body.sid)
                used.append({"tool": tc.function.name, "args": args, "result": res.get("found", res.get("success"))})
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(res)})
    except Exception as e:
        print("LLM error:", e)
    return {"reply": "Sorry, I had a small technical issue. Could you please say that again?", "tools": used}

class Summ(BaseModel):
    transcript: list[dict]

@app.post("/api/summary")
def summary(body: Summ):
    text = "\n".join(f"{t['role']}: {t['text']}" for t in body.transcript)
    prompt = ("Summarise this support call as JSON only with keys: customer_intent (ORDER_TRACKING, CANCELLATION, "
              "RETURN_REFUND, POLICY_QUERY, OUT_OF_SCOPE or OTHER), order_id (string or null), resolution_status "
              "(RESOLVED, UNRESOLVED or ESCALATED), call_summary (1-2 sentences).\n\n" + text)
    try:
        r = complete(temperature=0, max_tokens=800,
                                           response_format={"type": "json_object"},
                                           messages=[{"role": "user", "content": prompt}])
        return json.loads(r.choices[0].message.content)
    except Exception as e:
        return {"customer_intent": "OTHER", "order_id": None, "resolution_status": "UNRESOLVED",
                "call_summary": f"Summary unavailable ({e})"}

class TTS(BaseModel):
    text: str

@app.post("/api/tts")
def tts(body: TTS):
    """Indian-English neural voice (Sarvam AI). The browser falls back to its own voice if this fails."""
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise HTTPException(503, "TTS not configured")
    try:
        r = httpx.post("https://api.sarvam.ai/text-to-speech", timeout=15,
                       headers={"api-subscription-key": key},
                       json={"text": body.text[:1000], "target_language_code": "en-IN",
                             "speaker": os.getenv("TTS_SPEAKER", "priya"),
                             "model": os.getenv("TTS_MODEL", "bulbul:v3")})
        if r.status_code != 200:
            print("TTS error:", r.status_code, r.text)  # shows Sarvam's exact complaint
            raise HTTPException(502, "TTS failed")
        return Response(base64.b64decode(r.json()["audios"][0]), media_type="audio/wav")
    except HTTPException:
        raise
    except Exception as e:
        print("TTS error:", e)
        raise HTTPException(502, "TTS failed")

@app.get("/")
def index():
    return FileResponse("static/index.html")

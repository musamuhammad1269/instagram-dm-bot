"""
Maddy Burgers - Instagram DM AI Agent
Handles customer inquiries, reservations, and orders via Instagram DMs
Uses the official Meta Instagram Messaging API (webhook-based)
"""

from dotenv import load_dotenv
load_dotenv()
import os
import json
import random
import string
import requests
from datetime import datetime
from anthropic import Anthropic
import gspread
from google.oauth2.service_account import Credentials
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
import uvicorn


# ─── CONFIG ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_SHEET_ID    = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDS_FILE  = os.environ.get("GOOGLE_CREDS_FILE", "google_credentials.json")
IG_USER_ID         = os.environ["IG_USER_ID"]          # Instagram Business Account ID
PAGE_ACCESS_TOKEN  = os.environ["PAGE_ACCESS_TOKEN"]   # Meta Page Access Token
VERIFY_TOKEN       = os.environ["VERIFY_TOKEN"]        # Any secret string you choose
PORT               = int(os.environ.get("PORT", "8000"))
GRAPH_API_VERSION  = "v19.0"

# ─── RESTAURANT DATA ───────────────────────────────────────────────────────────

RESTAURANT_INFO = """
RESTAURANT: Maddy Burgers 🍔
TAGLINE: "Smashed, Stacked & Obsessed"

📍 LOCATION: 47 Flame Street, Downtown, NY 10001
📞 PHONE: +1 (212) 555-BRGR
🕐 HOURS: Mon-Thu 11am–10pm | Fri-Sat 11am–12am | Sun 12pm–9pm
🚗 DELIVERY: Available via DoorDash and UberEats

---
FULL MENU:

🔥 SIGNATURE BURGERS
- The Maddy Classic         $12.99  | Double smash patty, american cheese, secret sauce, pickles, onions
- The Fire Stack            $15.99  | Triple patty, pepper jack, jalapeños, sriracha aioli, crispy onions
- The Truffle Shuffle        $16.99  | Wagyu patty, truffle mayo, gruyère, caramelized onions, arugula
- The Smoky BBQ Boss        $14.99  | Smoked brisket patty, cheddar, bacon, BBQ sauce, coleslaw
- The Mushroom Meltdown     $13.99  | Double patty, sautéed mushrooms, swiss cheese, garlic aioli
- The Veggie Vibe 🌱        $12.99  | Beyond Meat patty, avocado, tomato, lettuce, vegan mayo

🍟 SIDES
- Classic Fries             $4.99
- Truffle Parmesan Fries    $6.99
- Onion Rings               $5.99
- Sweet Potato Fries        $5.99
- Mac & Cheese Bites        $6.99
- Side Salad                $4.99

🥤 DRINKS
- Fountain Drinks           $2.99  | Coke, Diet Coke, Sprite, Lemonade
- Milkshakes                $6.99  | Vanilla, Chocolate, Strawberry, Oreo, Salted Caramel
- Fresh Lemonade            $3.99
- Bottled Water             $1.99

🍺 ALCOHOLIC BEVERAGES (Dine-in only, ID required)
- Draft Beer                $6.99  | IPA, Lager, Wheat
- Craft Cans                $7.99
- House Wine                $8.99  | Red, White, Rosé

🤤 COMBOS (Save up to $4!)
- Classic Combo             $16.99  | Maddy Classic + Fries + Fountain Drink
- Fire Combo                $19.99  | Fire Stack + Truffle Fries + Milkshake
- Veggie Combo 🌱           $15.99  | Veggie Vibe + Sweet Potato Fries + Lemonade

---
CURRENT DEALS & PROMOTIONS:
🎉 HAPPY HOUR: Mon-Fri 3pm–5pm → 20% off all orders
🎂 BIRTHDAY DEAL: Free shake on your birthday (show ID)
📱 SOCIAL SPECIAL: Follow @maddy_burgers → $2 off first order (use code: MADDYFAM)
🔟 LOYALTY: Buy 9 burgers, get the 10th free (stamp card available at register)
👨‍👩‍👧 FAMILY BUNDLE: 4 Classic Combos for $59.99 (save $8)

---
RESERVATION POLICY:
- Reservations available for groups of 2–20
- Walk-ins welcome but may have wait times on weekends
- Cancellations: Please cancel at least 2 hours in advance
- Private events: Contact us for large group bookings (20+)

---
ALLERGEN INFO:
- All burgers can be made gluten-free (GF bun, +$1.50)
- Nut-free kitchen
- Vegetarian/vegan options available
- Ask staff about specific allergen needs
"""

SYSTEM_PROMPT = f"""You are MaddyBot 🍔, the friendly AI assistant for Maddy Burgers restaurant on Instagram.
You live in Instagram DMs and help customers with menu info, reservations, and orders.

RESTAURANT KNOWLEDGE:
{RESTAURANT_INFO}

YOUR CAPABILITIES:
1. Answer questions about the menu, pricing, hours, location, deals, allergens
2. Take DELIVERY or TAKEAWAY orders (not for dine-in via DM)
3. Make RESERVATIONS for dine-in
4. Provide ORDER STATUS updates when customer gives their Order ID
5. Handle general FAQs

PERSONALITY:
- Warm, enthusiastic, use burger/food emojis naturally 🍔🔥✨
- Keep responses concise but friendly — this is Instagram DM, not email
- Use casual language, not corporate speak
- When unsure, say so honestly and offer to connect them with the team

TAKING AN ORDER — COLLECT THIS INFO:
1. Items + quantities (reference exact menu names)
2. Order type: Delivery or Takeaway?
3. If delivery: full delivery address
4. If takeaway: preferred pickup time
5. Customer name
6. Contact number (for order updates)
7. Any special requests (e.g., no pickles, extra sauce)
8. Confirm the total price before finalizing

MAKING A RESERVATION — COLLECT THIS INFO:
1. Date and time
2. Number of guests
3. Customer name
4. Contact number
5. Any special requests (birthday, dietary needs, etc.)

IMPORTANT RULES:
- Never make up menu items or prices not listed above
- Never promise something you cannot guarantee (exact wait times, etc.)
- For complaints or serious issues, always offer to escalate: "I'll flag this for our team right away!"
- Order IDs look like: MB-XXXXXX (6 alphanumeric characters)
- When a customer provides an Order ID, use the check_order_status function
- When an order is confirmed, use the create_order function
- When a reservation is confirmed, use the create_reservation function
- Do NOT ask for payment details — payment is handled at pickup/delivery

RESPONSE FORMAT:
- Keep DM responses under 200 words usually
- Use line breaks for readability
- Sign off warmly, invite follow-up questions
"""

# ─── GOOGLE SHEETS ─────────────────────────────────────────────────────────────

def get_sheets_client():
    """Return authenticated gspread client."""
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scopes=scopes)
    return gspread.authorize(creds)

def get_or_create_sheet(gc, sheet_id, tab_name, headers):
    """Get worksheet by name, create with headers if missing."""
    spreadsheet = gc.open_by_key(sheet_id)
    try:
        ws = spreadsheet.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=len(headers))
        ws.append_row(headers)
    return ws

def generate_order_id():
    chars = string.ascii_uppercase + string.digits
    return "MB-" + "".join(random.choices(chars, k=6))

def create_order(order_data: dict) -> dict:
    """Write a new order to Google Sheets and return the order ID."""
    try:
        gc = get_sheets_client()
        headers = [
            "Order ID", "Timestamp", "Instagram User", "Customer Name",
            "Phone", "Order Type", "Delivery Address / Pickup Time",
            "Items", "Total", "Special Requests", "Status"
        ]
        ws = get_or_create_sheet(gc, GOOGLE_SHEET_ID, "Orders", headers)

        order_id = generate_order_id()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        row = [
            order_id,
            now,
            order_data.get("instagram_user", ""),
            order_data.get("customer_name", ""),
            order_data.get("phone", ""),
            order_data.get("order_type", ""),
            order_data.get("address_or_pickup_time", ""),
            order_data.get("items", ""),
            order_data.get("total", ""),
            order_data.get("special_requests", ""),
            "Received",
        ]
        ws.append_row(row)
        return {"success": True, "order_id": order_id}
    except Exception as e:
        return {"success": False, "error": str(e)}

def check_order_status(order_id: str, instagram_user: str) -> dict:
    """Look up order status from Google Sheets."""
    try:
        gc = get_sheets_client()
        spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)
        ws = spreadsheet.worksheet("Orders")
        records = ws.get_all_records()

        for record in records:
            if record.get("Order ID", "").upper() == order_id.upper():
                return {
                    "found": True,
                    "order_id": record["Order ID"],
                    "status": record.get("Status", "Unknown"),
                    "items": record.get("Items", ""),
                    "order_type": record.get("Order Type", ""),
                    "timestamp": record.get("Timestamp", ""),
                }
        return {"found": False, "order_id": order_id}
    except Exception as e:
        return {"found": False, "error": str(e)}

def create_reservation(reservation_data: dict) -> dict:
    """Write a new reservation to Google Sheets."""
    try:
        gc = get_sheets_client()
        headers = [
            "Reservation ID", "Timestamp", "Instagram User", "Customer Name",
            "Phone", "Date", "Time", "Guests", "Special Requests", "Status"
        ]
        ws = get_or_create_sheet(gc, GOOGLE_SHEET_ID, "Reservations", headers)

        res_id = "RES-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        row = [
            res_id,
            now,
            reservation_data.get("instagram_user", ""),
            reservation_data.get("customer_name", ""),
            reservation_data.get("phone", ""),
            reservation_data.get("date", ""),
            reservation_data.get("time", ""),
            reservation_data.get("guests", ""),
            reservation_data.get("special_requests", ""),
            "Confirmed",
        ]
        ws.append_row(row)
        return {"success": True, "reservation_id": res_id}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ─── CLAUDE TOOLS ──────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "create_order",
        "description": "Creates a new food order and saves it to Google Sheets. Call this only after collecting ALL required order details and the customer has confirmed the order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "instagram_user":          {"type": "string", "description": "Customer's Instagram username"},
                "customer_name":           {"type": "string", "description": "Customer's real name"},
                "phone":                   {"type": "string", "description": "Customer's contact number"},
                "order_type":              {"type": "string", "enum": ["Delivery", "Takeaway"], "description": "Delivery or Takeaway"},
                "address_or_pickup_time":  {"type": "string", "description": "Delivery address OR preferred pickup time"},
                "items":                   {"type": "string", "description": "Comma-separated list of items and quantities, e.g. '2x Maddy Classic, 1x Truffle Fries, 2x Milkshake'"},
                "total":                   {"type": "string", "description": "Total price as a string, e.g. '$38.97'"},
                "special_requests":        {"type": "string", "description": "Any special requests or dietary needs. 'None' if not applicable."},
            },
            "required": ["instagram_user", "customer_name", "phone", "order_type", "address_or_pickup_time", "items", "total"],
        },
    },
    {
        "name": "check_order_status",
        "description": "Checks the status of an existing order by Order ID. Use when a customer asks about their order status and provides an Order ID like MB-XXXXXX.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id":       {"type": "string", "description": "The Order ID, e.g. MB-ABC123"},
                "instagram_user": {"type": "string", "description": "The customer's Instagram username"},
            },
            "required": ["order_id", "instagram_user"],
        },
    },
    {
        "name": "create_reservation",
        "description": "Creates a table reservation and saves it to Google Sheets. Call this after collecting all reservation details and customer has confirmed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "instagram_user":   {"type": "string", "description": "Customer's Instagram username"},
                "customer_name":    {"type": "string", "description": "Customer's real name"},
                "phone":            {"type": "string", "description": "Customer's contact number"},
                "date":             {"type": "string", "description": "Reservation date, e.g. '2024-12-25'"},
                "time":             {"type": "string", "description": "Reservation time, e.g. '7:00 PM'"},
                "guests":           {"type": "string", "description": "Number of guests"},
                "special_requests": {"type": "string", "description": "Special requests like birthday, dietary needs. 'None' if not applicable."},
            },
            "required": ["instagram_user", "customer_name", "phone", "date", "time", "guests"],
        },
    },
]

# ─── CONVERSATION MANAGER ──────────────────────────────────────────────────────

class ConversationManager:
    """Maintains per-user conversation history in memory."""

    def __init__(self):
        self.histories: dict[str, list] = {}

    def get_history(self, user_id: str) -> list:
        return self.histories.get(user_id, [])

    def add_message(self, user_id: str, role: str, content):
        if user_id not in self.histories:
            self.histories[user_id] = []
        self.histories[user_id].append({"role": role, "content": content})
        # Keep last 40 messages to stay within context
        if len(self.histories[user_id]) > 40:
            self.histories[user_id] = self.histories[user_id][-40:]

# ─── AGENT CORE ────────────────────────────────────────────────────────────────

class MaddyBurgersAgent:
    def __init__(self):
        self.client     = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.conv_mgr   = ConversationManager()

    def process_tool_call(self, tool_name: str, tool_input: dict) -> str:
        if tool_name == "create_order":
            result = create_order(tool_input)
        elif tool_name == "check_order_status":
            result = check_order_status(tool_input["order_id"], tool_input["instagram_user"])
        elif tool_name == "create_reservation":
            result = create_reservation(tool_input)
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
        return json.dumps(result)

    def chat(self, instagram_user: str, user_message: str) -> str:
        """Send a message and get a response, handling tool use."""
        self.conv_mgr.add_message(instagram_user, "user", user_message)

        messages = self.conv_mgr.get_history(instagram_user)

        while True:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            # Append assistant turn
            self.conv_mgr.add_message(instagram_user, "assistant", response.content)

            if response.stop_reason == "tool_use":
                # Process all tool calls
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result_str = self.process_tool_call(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        })

                # Add tool results and loop
                self.conv_mgr.add_message(instagram_user, "user", tool_results)
                messages = self.conv_mgr.get_history(instagram_user)

            else:
                # Extract final text response
                text_parts = [b.text for b in response.content if hasattr(b, "text")]
                return "\n".join(text_parts).strip()

# ─── INSTAGRAM MESSAGING API ───────────────────────────────────────────────────

def send_instagram_reply(recipient_id: str, text: str) -> bool:
    """Send a DM reply via the official Meta Graph API."""
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{IG_USER_ID}/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }
    headers = {"Authorization": f"Bearer {PAGE_ACCESS_TOKEN}"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"Failed to send reply to {recipient_id}: {e}")
        return False

# ─── WEBHOOK SERVER ─────────────────────────────────────────────────────────────

app   = FastAPI()
agent = MaddyBurgersAgent()

@app.get("/webhook")
async def verify_webhook(request: Request):
    """Meta webhook verification handshake."""
    params     = request.query_params
    mode       = params.get("hub.mode")
    token      = params.get("hub.verify_token")
    challenge  = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified.")
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Verification failed")

@app.post("/webhook")
async def handle_webhook(request: Request):
    """Receive incoming DM events from Meta and reply."""
    body = await request.json()

    for entry in body.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            message   = event.get("message", {})
            text      = message.get("text")

            # Ignore echoes (our own sent messages) and non-text events
            if not text or message.get("is_echo"):
                continue

            print(f"📩 [{sender_id}]: {text[:80]}")

            reply = agent.chat(sender_id, text)
            print(f"🤖 Reply: {reply[:80]}")

            send_instagram_reply(sender_id, reply)

    return {"status": "ok"}

if __name__ == "__main__":
    print("🍔 Maddy Burgers DM Agent starting...")
    uvicorn.run(app, host="0.0.0.0", port=PORT)

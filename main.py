#!/usr/bin/env python3
"""
◈ PREMIUM SHOP BOT – Modern Design Edition
Railway-ready · Echte LTC Blockchain-Verifizierung
"""

import json, os, time, asyncio, logging, aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# KONFIGURATION
# ══════════════════════════════════════════════════════════

BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
# Sicherer Import der Admin-IDs
ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip()]

DATA_DIR   = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", ".")
DATA_FILE  = os.path.join(DATA_DIR, "shop_data.json")
PEND_FILE  = os.path.join(DATA_DIR, "pending_orders.json")
SHOP_NAME  = os.environ.get("SHOP_NAME", "PREMIUM STORE")

CHECK_INTERVAL = 30
ORDER_TIMEOUT  = 3600
LTC_TOLERANCE  = 0.0001

# States
(ADMIN_MENU, ADD_NAME, ADD_DESC, ADD_PRICE,
ADD_STOCK, SET_LTC, RESTOCK_SELECT, RESTOCK_AMOUNT) = range(8)

# ── Design ────────────────────────────────────────────────

LINE_HEAVY = "━━━━━━━━━━━━━━━━━━━━━━"
def box(title, emoji="◈"):
    return f"◈ {LINE_HEAVY} ◈\n    {emoji}  {title}\n◈ {LINE_HEAVY} ◈"

# ── Daten ─────────────────────────────────────────────────

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f: return json.load(f)
    return {"products": {}, "ltc_address": "", "orders": []}

def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f: json.dump(d, f, indent=2)

def load_pending():
    if os.path.exists(PEND_FILE):
        with open(PEND_FILE, "r", encoding="utf-8") as f: return json.load(f)
    return {}

def save_pending(p):
    with open(PEND_FILE, "w", encoding="utf-8") as f: json.dump(p, f, indent=2)

# ── Admin Check ───────────────────────────────────────────

def is_admin(user_id):
    return int(user_id) in ADMIN_IDS

# ── Blockchain API ────────────────────────────────────────

async def get_incoming_ltc(address, since_ts):
    url = f"https://api.blockcypher.com/v1/ltc/main/addrs/{address}/full?limit=50"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=10) as r:
                if r.status != 200: return []
                raw = await r.json()
                out = []
                for tx in raw.get("txs", []):
                    import datetime
                    dt = datetime.datetime.fromisoformat(tx.get("received", "").replace("Z", "+00:00"))
                    if int(dt.timestamp()) < since_ts: continue
                    sat = sum(o.get("value", 0) for o in tx.get("outputs", []) if address in o.get("addresses", []))
                    if sat > 0:
                        out.append({"txid": tx.get("hash", ""), "amount_ltc": round(sat/1e8, 8)})
                return out
    except: return []

# ── Payment Loop ──────────────────────────────────────────

async def payment_checker_loop(app):
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            pending = load_pending()
            data = load_data()
            if not pending or not data.get("ltc_address"): continue
            txs = await get_incoming_ltc(data["ltc_address"], int(time.time()) - ORDER_TIMEOUT)
            used = {o.get("txid") for o in data.get("orders", [])}
            
            for oid, order in list(pending.items()):
                for tx in txs:
                    if tx["txid"] not in used and abs(tx["amount_ltc"] - float(order["price"])) <= LTC_TOLERANCE:
                        p = data["products"].get(order["product_id"])
                        if p and p["items"]:
                            item = p["items"].pop(0)
                            data["orders"].append({"txid": tx["txid"], "item": item})
                            save_data(data)
                            await app.bot.send_message(order["user_id"], f"✅ Zahlung erhalten!\nDein Key: `{item}`", parse_mode="Markdown")
                            pending.pop(oid)
                            save_pending(pending)
                            break
        except Exception as e: logger.error(f"Error: {e}")

# ── Handlers ──────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    kb = [[InlineKeyboardButton(f"{p['name']} ({p['price']} LTC)", callback_data=f"buy_{pid}")] for pid, p in data["products"].items()]
    await update.message.reply_text(f"Welcome to {SHOP_NAME}", reply_markup=InlineKeyboardMarkup(kb))

async def buy_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pid = query.data.replace("buy_", "")
    data = load_data()
    p = data["products"].get(pid)
    order_id = str(int(time.time()))
    pending = load_pending()
    pending[order_id] = {"user_id": query.from_user.id, "product_id": pid, "price": p["price"], "created_at": int(time.time())}
    save_pending(pending)
    await query.edit_message_text(f"Bitte {p['price']} LTC an `{data['ltc_address']}` senden.", parse_mode="Markdown")

# ── Admin Logik ───────────────────────────────────────────

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    logger.info(f"Admin-Check: User {uid} versucht Zugriff. Erlaubte IDs: {ADMIN_IDS}")
    
    if not is_admin(uid):
        await update.message.reply_text("🔒 Kein Zugriff. Deine ID ist nicht in ADMIN_IDS.")
        return ConversationHandler.END
    
    kb = [
        [InlineKeyboardButton("➕ Produkt erstellen", callback_data="admin_add")],
        [InlineKeyboardButton("📦 Lager auffüllen", callback_data="admin_restock")],
        [InlineKeyboardButton("💳 LTC Adresse setzen", callback_data="admin_ltc")]
    ]
    await update.message.reply_text(box("ADMIN PANEL", "⚙️"), reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ADMIN_MENU

async def admin_handle_calls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "admin_add":
        await query.edit_message_text("Name des Produkts?")
        return ADD_NAME
    elif query.data == "admin_ltc":
        await query.edit_message_text("Sende die LTC Adresse:")
        return SET_LTC
    elif query.data == "admin_restock":
        data = load_data()
        kb = [[InlineKeyboardButton(p["name"], callback_data=f"rs_{pid}")] for pid, p in data["products"].items()]
        await query.edit_message_text("Welches Produkt auffüllen?", reply_markup=InlineKeyboardMarkup(kb))
        return RESTOCK_SELECT

async def set_ltc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data(); data["ltc_address"] = update.message.text.strip(); save_data(data)
    await update.message.reply_text("✅ Adresse gespeichert."); return ConversationHandler.END

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["np"] = {"name": update.message.text.strip()}
    await update.message.reply_text("Preis in LTC (z.B. 0.05)?"); return ADD_PRICE

async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["np"]["price"] = update.message.text.strip()
    await update.message.reply_text("Sende die Artikel (einer pro Zeile):"); return ADD_STOCK

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = [l.strip() for l in update.message.text.split("\n") if l.strip()]
    data = load_data(); pid = str(int(time.time()))
    data["products"][pid] = context.user_data["np"]; data["products"][pid]["description"] = ""; data["products"][pid]["items"] = items
    save_data(data); await update.message.reply_text("✅ Produkt erstellt!"); return ConversationHandler.END

async def restock_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["r_pid"] = update.callback_query.data.replace("rs_", "")
    await update.callback_query.edit_message_text("Sende die neuen Artikel (einer pro Zeile):")
    return RESTOCK_AMOUNT

async def restock_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = [l.strip() for l in update.message.text.split("\n") if l.strip()]
    data = load_data(); data["products"][context.user_data["r_pid"]]["items"].extend(items); save_data(data)
    await update.message.reply_text("✅ Lager aufgefüllt."); return ConversationHandler.END

# ── Main ──────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_start)],
        states={
            ADMIN_MENU: [CallbackQueryHandler(admin_handle_calls)],
            SET_LTC: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_ltc)],
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)],
            ADD_STOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_stock)],
            RESTOCK_SELECT: [CallbackQueryHandler(restock_select)],
            RESTOCK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, restock_amount)],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
    )

    app.add_handler(admin_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buy_product, pattern="^buy_"))

    app.post_init = lambda a: asyncio.create_task(payment_checker_loop(a))
    app.run_polling()

if __name__ == "__main__":
    main()

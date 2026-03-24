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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# KONFIGURATION (Umgebungsvariablen)
# ══════════════════════════════════════════════════════════

BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS  = [int(x) for x in os.environ.get("ADMIN_IDS","").split(",") if x.strip()]
DATA_DIR   = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", ".")
DATA_FILE  = os.path.join(DATA_DIR, "shop_data.json")
PEND_FILE  = os.path.join(DATA_DIR, "pending_orders.json")
SHOP_NAME  = os.environ.get("SHOP_NAME", "PREMIUM STORE")
CHECK_INTERVAL = 30
ORDER_TIMEOUT  = 3600
LTC_TOLERANCE  = 0.0001

# States für ConversationHandler
(ADMIN_MENU, ADD_NAME, ADD_DESC, ADD_PRICE,
ADD_STOCK, SET_LTC, RESTOCK_SELECT, RESTOCK_AMOUNT) = range(8)

# ── Design Tokens ──────────────────────────────────────────

LINE_HEAVY = "━━━━━━━━━━━━━━━━━━━━━━"
LINE_LIGHT = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
CORNER_TL  = "╭"
CORNER_TR  = "╮"
CORNER_BL  = "╰"
CORNER_BR  = "╯"
SIDE       = "│"

def box(title, emoji="◈"):
    return f"◈ {LINE_HEAVY} ◈\n    {emoji}  {title}\n◈ {LINE_HEAVY} ◈"

def card(lines):
    inner = "\n".join(f"{SIDE}  {l}" for l in lines)
    top   = f"{CORNER_TL}{LINE_LIGHT}{CORNER_TR}"
    bot   = f"{CORNER_BL}{LINE_LIGHT}{CORNER_BR}"
    return f"{top}\n{inner}\n{bot}"

def stock_bar(n, width=8):
    filled = min(n, width)
    return "█" * filled + "░" * (width - filled)

# ── Datenverwaltung ────────────────────────────────────────

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return {"products": {}, "ltc_address": "", "orders": []}

def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f: 
        json.dump(d, f, indent=2, ensure_ascii=False)

def load_pending():
    if os.path.exists(PEND_FILE):
        try:
            with open(PEND_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return {}

def save_pending(p):
    with open(PEND_FILE, "w", encoding="utf-8") as f: 
        json.dump(p, f, indent=2, ensure_ascii=False)

def is_admin(uid): return uid in ADMIN_IDS

# ── Blockchain Logik ───────────────────────────────────────

async def get_incoming_ltc(address, since_ts):
    url = f"https://api.blockcypher.com/v1/ltc/main/addrs/{address}/full?limit=50"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200: return []
                raw = await r.json()
                import datetime
                out = []
                for tx in raw.get("txs", []):
                    try:
                        dt = datetime.datetime.fromisoformat(tx.get("received", "").replace("Z", "+00:00"))
                        ts = int(dt.timestamp())
                    except: ts = 0
                    if ts < since_ts: continue
                    sat = sum(o.get("value", 0) for o in tx.get("outputs", []) if address in o.get("addresses", []))
                    if sat > 0:
                        out.append({"txid": tx.get("hash", ""), "amount_ltc": round(sat/1e8, 8), "confirmations": tx.get("confirmations", 0)})
                return out
    except Exception as e:
        logger.error(f"BlockCypher Error: {e}"); return []

# ── Payment Checker ────────────────────────────────────────

async def payment_checker_loop(app):
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            pending = load_pending()
            data    = load_data()
            addr    = data.get("ltc_address", "")
            if not pending or not addr: continue
            
            now = int(time.time())
            txs = await get_incoming_ltc(addr, now - ORDER_TIMEOUT)
            used = {o.get("txid") for o in data.get("orders", []) if o.get("txid")}
            remove = []

            for oid, order in list(pending.items()):
                if now - order["created_at"] > ORDER_TIMEOUT:
                    remove.append(oid)
                    try:
                        await app.bot.send_message(order["user_id"], "⏰ Bestellung abgelaufen.")
                    except: pass
                    continue

                exp = float(order["price"])
                for tx in txs:
                    if tx["txid"] in used: continue
                    if abs(tx["amount_ltc"] - exp) > LTC_TOLERANCE: continue

                    pid = order["product_id"]
                    p = data["products"].get(pid)
                    if not p or not p.get("items"):
                        remove.append(oid); break

                    item = p["items"].pop(0)
                    data["orders"].append({
                        "user_id": order["user_id"], "username": order.get("username", ""),
                        "product": p["name"], "price": order["price"],
                        "item": item, "txid": tx["txid"], "timestamp": now
                    })
                    used.add(tx["txid"])
                    save_data(data)
                    remove.append(oid)

                    try:
                        await app.bot.send_message(order["user_id"],
                            f"{box('ZAHLUNG BESTÄTIGT', '✅')}\n\n"
                            f"📦 Produkt: *{p['name']}*\n"
                            f"💎 Betrag: `{tx['amount_ltc']} LTC`\n\n"
                            f"✦ *DEIN ARTIKEL:*\n`{item}`",
                            parse_mode="Markdown")
                    except: pass
                    break

            for oid in remove: pending.pop(oid, None)
            save_pending(pending)
        except Exception as e:
            logger.error(f"Checker error: {e}")

# ── Shop Handlers ──────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = update.effective_user
    total_stock = sum(len(p.get("items", [])) for p in data["products"].values())

    header = f"◈ {LINE_HEAVY} ◈\n      ✦  {SHOP_NAME}  ✦\n◈ {LINE_HEAVY} ◈\n\n"
    header += f"Hey *{user.first_name}* 👋\n\n"

    if not data["products"]:
        await update.message.reply_text(header + "🚫 Aktuell keine Produkte verfügbar.", parse_mode="Markdown")
        return

    keyboard = []
    for pid, p in data["products"].items():
        stock = len(p.get("items", []))
        label = f"✦ {p['name']} · {p['price']} LTC · ✅ {stock}x" if stock > 0 else f"○ {p['name']} · Ausverkauft"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"product_{pid}")])
    keyboard.append([InlineKeyboardButton("🔄 Aktualisieren", callback_data="refresh_shop")])

    await update.message.reply_text(header + "Wähle ein Produkt:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.replace("product_", "")
    data = load_data()
    p = data["products"].get(pid)
    if not p: return

    stock = len(p.get("items", []))
    text = f"{box(p['name'].upper(), '📦')}\n\n{p['description']}\n\n💎 Preis: `{p['price']} LTC`"
    
    keyboard = []
    if stock > 0 and data.get("ltc_address"):
        keyboard.append([InlineKeyboardButton("⚡ JETZT KAUFEN ⚡", callback_data=f"buy_{pid}")])
    keyboard.append([InlineKeyboardButton("◂ Zurück", callback_data="back_shop")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def buy_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.replace("buy_", "")
    data = load_data()
    p = data["products"].get(pid)
    ltc = data.get("ltc_address", "")
    
    user = query.from_user
    order_id = f"{user.id}_{int(time.time())}"
    pending = load_pending()
    pending[order_id] = {
        "user_id": user.id, "username": user.username or user.first_name,
        "product_id": pid, "product_name": p["name"],
        "price": p["price"], "created_at": int(time.time())
    }
    save_pending(pending)

    text = f"{box('ZAHLUNG', '⚡')}\n\nSende exakt `{p['price']} LTC` an:\n\n`{ltc}`"
    keyboard = [[InlineKeyboardButton("✗ Stornieren", callback_data=f"cancel_{order_id}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pending = load_pending()
    pending.pop(query.data.replace("cancel_", ""), None)
    save_pending(pending)
    await query.edit_message_text("❌ Bestellung abgebrochen. /start", parse_mode="Markdown")

async def back_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await start(update, context)

async def refresh_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await query.answer("Aktualisiert")
    await start(update, context)

# ── Admin Bereich ──────────────────────────────────────────

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return ConversationHandler.END
    await show_admin_menu(update, context)
    return ADMIN_MENU

async def show_admin_menu(update, context, edit=False):
    data = load_data()
    text = f"{box('ADMIN PANEL', '⚙️')}\n\nLagerbestand:\n"
    for pid, p in data["products"].items():
        text += f"- {p['name']}: {len(p['items'])}x\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ Produkt", callback_data="admin_add_product"),
         InlineKeyboardButton("📦 Restock", callback_data="admin_restock")],
        [InlineKeyboardButton("💳 LTC Adresse", callback_data="admin_set_ltc")]
    ]
    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "admin_set_ltc":
        await query.edit_message_text("Sende neue LTC Adresse:")
        return SET_LTC
    elif query.data == "admin_add_product":
        await query.edit_message_text("Name des Produkts?")
        return ADD_NAME
    elif query.data == "admin_restock":
        data = load_data()
        kb = [[InlineKeyboardButton(p["name"], callback_data=f"restock_{pid}")] for pid, p in data["products"].items()]
        await query.edit_message_text("Welches Produkt?", reply_markup=InlineKeyboardMarkup(kb))
        return RESTOCK_SELECT

async def set_ltc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data(); data["ltc_address"] = update.message.text.strip(); save_data(data)
    await update.message.reply_text("✅ Adresse gespeichert."); await show_admin_menu(update, context); return ADMIN_MENU

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["np"] = {"name": update.message.text.strip()}
    await update.message.reply_text("Beschreibung?"); return ADD_DESC

async def add_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["np"]["description"] = update.message.text.strip()
    await update.message.reply_text("Preis in LTC (z.B. 0.05)?"); return ADD_PRICE

async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["np"]["price"] = update.message.text.strip()
    await update.message.reply_text("Sende die Artikel (einer pro Zeile):"); return ADD_STOCK

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = [l.strip() for l in update.message.text.split("\n") if l.strip()]
    data = load_data(); pid = str(int(time.time()))
    data["products"][pid] = context.user_data["np"]; data["products"][pid]["items"] = items
    save_data(data); await update.message.reply_text("✅ Produkt erstellt."); await show_admin_menu(update, context); return ADMIN_MENU

async def restock_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["r_pid"] = query.data.replace("restock_", "")
    await query.edit_message_text("Sende die neuen Artikel:")
    return RESTOCK_AMOUNT

async def restock_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data["r_pid"]
    items = [l.strip() for l in update.message.text.split("\n") if l.strip()]
    data = load_data()
    if pid in data["products"]:
        data["products"][pid]["items"].extend(items)
        save_data(data)
    await update.message.reply_text("✅ Lager aufgefüllt."); await show_admin_menu(update, context); return ADMIN_MENU

# ── Main ───────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin)],
        states={
            ADMIN_MENU: [CallbackQueryHandler(admin_callback)],
            SET_LTC: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_ltc)],
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ADD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_desc)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)],
            ADD_STOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_stock)],
            RESTOCK_SELECT: [CallbackQueryHandler(restock_select)],
            RESTOCK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, restock_amount)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(show_product, pattern="^product_"))
    app.add_handler(CallbackQueryHandler(buy_product, pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(cancel_order, pattern="^cancel_"))
    app.add_handler(CallbackQueryHandler(back_shop, pattern="^back_shop$"))

    async def init_checker(app):
        asyncio.create_task(payment_checker_loop(app))
    app.post_init = init_checker

    print("Bot gestartet...")
    app.run_polling()

if __name__ == "__main__":
    main()

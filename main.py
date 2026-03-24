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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# ══════════════════════════════════════════════════════════

(ADMIN_MENU, ADD_NAME, ADD_DESC, ADD_PRICE,
ADD_STOCK, SET_LTC, RESTOCK_SELECT, RESTOCK_AMOUNT) = range(8)

# ── Design Tokens ──────────────────────────────────────────

LINE_HEAVY = "━━━━━━━━━━━━━━━━━━━━━━"
LINE_LIGHT = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
LINE_DOUBLE= "══════════════════════"
CORNER_TL  = "╭"
CORNER_TR  = "╮"
CORNER_BL  = "╰"
CORNER_BR  = "╯"
SIDE       = "│"

def box(title, emoji="◈"):
    return f"◈ {LINE_HEAVY} ◈\n    {emoji}  {title}\n◈ {LINE_HEAVY} ◈"

def card(lines):
    """Render a card with border"""
    inner = "\n".join(f"{SIDE}  {l}" for l in lines)
    top   = f"{CORNER_TL}{LINE_LIGHT}{CORNER_TR}"
    bot   = f"{CORNER_BL}{LINE_LIGHT}{CORNER_BR}"
    return f"{top}\n{inner}\n{bot}"

def stock_bar(n, width=8):
    filled = min(n, width)
    return "█" * filled + "░" * (width - filled)

# ── Data ──────────────────────────────────────────────────

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE,"r",encoding="utf-8") as f: return json.load(f)
    return {"products":{},"ltc_address":"","orders":[]}

def save_data(d):
    with open(DATA_FILE,"w",encoding="utf-8") as f: json.dump(d,f,indent=2,ensure_ascii=False)

def load_pending():
    if os.path.exists(PEND_FILE):
        with open(PEND_FILE,"r",encoding="utf-8") as f: return json.load(f)
    return {}

def save_pending(p):
    with open(PEND_FILE,"w",encoding="utf-8") as f: json.dump(p,f,indent=2,ensure_ascii=False)

def is_admin(uid): return uid in ADMIN_IDS

# ── Blockchain ─────────────────────────────────────────────

async def get_incoming_ltc(address, since_ts):
    url = f"https://api.blockcypher.com/v1/ltc/main/addrs/{address}/full?limit=50"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200: return []
                raw = await r.json()
                import datetime
                out = []
                for tx in raw.get("txs",[]):
                    try:
                        dt = datetime.datetime.fromisoformat(tx.get("received","").replace("Z","+00:00"))
                        ts = int(dt.timestamp())
                    except: ts = 0
                    if ts < since_ts: continue
                    sat = sum(o.get("value",0) for o in tx.get("outputs",[]) if address in o.get("addresses",[]))
                    if sat > 0:
                        out.append({"txid":tx.get("hash",""),"amount_ltc":round(sat/1e8,8),"confirmations":tx.get("confirmations",0)})
                return out
    except Exception as e:
        logger.error(f"BlockCypher: {e}"); return []

# ── Payment Loop ───────────────────────────────────────────

async def payment_checker_loop(app):
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            pending = load_pending()
            data    = load_data()
            addr    = data.get("ltc_address","")
            if not pending or not addr: continue
            now    = int(time.time())
            txs    = await get_incoming_ltc(addr, now - ORDER_TIMEOUT)
            used   = {o.get("txid") for o in data.get("orders",[]) if o.get("txid")}
            remove = []

            for oid, order in list(pending.items()):
                if now - order["created_at"] > ORDER_TIMEOUT:
                    remove.append(oid)
                    try:
                        await app.bot.send_message(order["user_id"],
                            f"{box('BESTELLUNG ABGELAUFEN', '⏰')}\n\n"
                            f"Produkt: *{order['product_name']}*\n"
                            f"Starte neu mit /start",
                            parse_mode="Markdown")
                    except: pass
                    continue

                exp = float(order["price"])
                for tx in txs:
                    if tx["txid"] in used: continue
                    if abs(tx["amount_ltc"] - exp) > LTC_TOLERANCE: continue

                    pid = order["product_id"]
                    p   = data["products"].get(pid)
                    if not p or not p.get("items"):
                        for uid in [order["user_id"]] + ADMIN_IDS:
                            try:
                                await app.bot.send_message(uid,
                                    f"⚠️ *Zahlung erhalten* – Produkt ausverkauft!\n"
                                    f"User: @{order.get('username','?')} | {tx['amount_ltc']} LTC",
                                    parse_mode="Markdown")
                            except: pass
                        remove.append(oid); break

                    item = p["items"].pop(0)
                    data["orders"].append({
                        "user_id":order["user_id"],"username":order.get("username",""),
                        "product":p["name"],"price":order["price"],
                        "item":item,"txid":tx["txid"],"timestamp":now
                    })
                    used.add(tx["txid"])
                    save_data(data)
                    remove.append(oid)

                    try:
                        await app.bot.send_message(order["user_id"],
                            f"{box('ZAHLUNG BESTÄTIGT', '✅')}\n\n"
                            + card([
                                f"📦  Produkt:    *{p['name']}*",
                                f"💎  Betrag:     `{tx['amount_ltc']} LTC`",
                                f"✔️   Confirms:   {tx['confirmations']}",
                                f"🔗  TX:         `{tx['txid'][:18]}...`",
                            ]) +
                            f"\n\n✦  *DEIN ARTIKEL:*\n\n"
                            f"`{item}`\n\n"
                            f"_{LINE_LIGHT}_\n"
                            f"💾  Speichere diese Daten sicher!",
                            parse_mode="Markdown")
                    except: pass

                    for aid in ADMIN_IDS:
                        try:
                            await app.bot.send_message(aid,
                                f"{box('VERKAUF', '💰')}\n\n"
                                + card([
                                    f"👤  @{order.get('username','?')}",
                                    f"📦  {p['name']}",
                                    f"💎  {order['price']} LTC",
                                    f"📊  Restbestand: *{len(p['items'])}*",
                                ]),
                                parse_mode="Markdown")
                        except: pass
                    break

            for oid in remove: pending.pop(oid,None)
            save_pending(pending)
        except Exception as e:
            logger.error(f"Checker error: {e}")

# ── Customer Actions ──────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = update.effective_user
    total_stock = sum(len(p.get("items",[])) for p in data["products"].values())

    header = (
        f"◈ {LINE_HEAVY} ◈\n"
        f"      ✦  {SHOP_NAME}  ✦\n"
        f"◈ {LINE_HEAVY} ◈\n\n"
        f"Hey *{user.first_name}* 👋\n\n"
    )

    if not data["products"]:
        await update.message.reply_text(
            header + "🚫  Aktuell keine Produkte verfügbar.\nSchau bald wieder rein!",
            parse_mode="Markdown")
        return

    header += card([
        f"🗂  Produkte:   *{len(data['products'])}*",
        f"📦  Auf Lager:  *{total_stock}* Artikel",
        f"💎  Zahlung:    Litecoin (LTC)",
        f"⚡  Lieferung:  Automatisch",
    ]) + "\n\n✦  *Wähle dein Produkt:*"

    keyboard = []
    for pid, p in data["products"].items():
        stock = len(p.get("items",[]))
        if stock > 0:
            label = f"✦  {p['name']}  ·  {p['price']} LTC  ·  ✅ {stock}x"
        else:
            label = f"○  {p['name']}  ·  Ausverkauft"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"product_{pid}")])
    keyboard.append([InlineKeyboardButton("🔄  Aktualisieren", callback_data="refresh_shop")])

    await update.message.reply_text(
        header, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid  = query.data.replace("product_","")
    data = load_data()
    p    = data["products"].get(pid)
    if not p:
        await query.edit_message_text("❌  Produkt nicht mehr verfügbar.")
        return

    stock = len(p.get("items",[]))
    bar   = stock_bar(stock)
    avail = f"`[{bar}]`  {stock} verfügbar" if stock > 0 else "`[░░░░░░░░]`  Ausverkauft"

    text = (
        f"◈ {LINE_HEAVY} ◈\n"
        f"  📦  *{p['name'].upper()}*\n"
        f"◈ {LINE_HEAVY} ◈\n\n"
        f"_{p['description']}_\n\n"
        + card([
            f"💎  Preis:   `{p['price']} LTC`",
            f"📊  Lager:   {avail}",
        ]) +
        "\n"
    )

    keyboard = []
    if stock > 0 and data.get("ltc_address"):
        keyboard.append([InlineKeyboardButton("⚡  JETZT KAUFEN  ⚡", callback_data=f"buy_{pid}")])
    keyboard.append([InlineKeyboardButton("◂  Zurück zum Shop", callback_data="back_shop")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def buy_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid  = query.data.replace("buy_","")
    data = load_data()
    p    = data["products"].get(pid)
    if not p or not p.get("items"):
        await query.edit_message_text("❌  Leider ausverkauft!"); return
    ltc = data.get("ltc_address","")
    if not ltc:
        await query.edit_message_text("⚠️  Keine Zahlungsadresse."); return

    user     = query.from_user
    order_id = f"{user.id}_{int(time.time())}"
    pending  = load_pending()
    pending[order_id] = {
        "user_id":user.id,"username":user.username or user.first_name,
        "product_id":pid,"product_name":p["name"],
        "price":p["price"],"created_at":int(time.time())
    }
    save_pending(pending)

    text = (
        f"◈ {LINE_HEAVY} ◈\n"
        f"    ⚡  ZAHLUNG STARTEN  ⚡\n"
        f"◈ {LINE_HEAVY} ◈\n\n"
        f"Produkt:  *{p['name']}*\n\n"
        f"*SCHRITT 1* –  Betrag senden:\n\n"
        f"     💎  `{p['price']} LTC`\n\n"
        f"*SCHRITT 2* –  An diese Adresse:\n\n"
        f"`{ltc}`\n\n"
        + card([
            f"🔍  Check-Intervall:  {CHECK_INTERVAL} Sek.",
            f"⏰  Gültig:           60 Minuten",
            f"✅  Lieferung:        Automatisch",
            f"⚠️  Betrag:           Exakt senden!",
        ]) +
        "\n\n_Kein manuelles Bestätigen nötig – der Bot erkennt deine Zahlung automatisch._"
    )

    keyboard = [[InlineKeyboardButton("✗  Bestellung stornieren", callback_data=f"cancel_{order_id}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pending = load_pending()
    pending.pop(query.data.replace("cancel_",""), None)
    save_pending(pending)
    await query.edit_message_text(
        f"{box('STORNIERT', '✗')}\n\nDeine Bestellung wurde abgebrochen.\n\n/start  →  Neu beginnen",
        parse_mode="Markdown")

async def refresh_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("✅  Aktualisiert!")
    await back_shop(update, context)

async def back_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data  = load_data()
    total_stock = sum(len(p.get("items",[])) for p in data["products"].values())
    keyboard = []
    for pid, p in data["products"].items():
        stock = len(p.get("items",[]))
        label = f"✦  {p['name']}  ·  {p['price']} LTC  ·  ✅ {stock}x" if stock > 0 else f"○  {p['name']}  ·  Ausverkauft"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"product_{pid}")])
    keyboard.append([InlineKeyboardButton("🔄  Aktualisieren", callback_data="refresh_shop")])
    await query.edit_message_text(
        f"◈ {LINE_HEAVY} ◈\n"
        f"      ✦  {SHOP_NAME}  ✦\n"
        f"◈ {LINE_HEAVY} ◈\n\n"
        + card([f"🗂  Produkte: *{len(data['products'])}* ·  📦 *{total_stock}* auf Lager"]) +
        "\n\n✦  *Wähle dein Produkt:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown")

# ── Admin Actions ──────────────────────────────────────────

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            f"{box('ZUGRIFF VERWEIGERT', '🔒')}\n\nDu hast keine Berechtigung.",
            parse_mode="Markdown")
        return ConversationHandler.END
    await show_admin_menu(update, context)
    return ADMIN_MENU

async def show_admin_menu(update, context, edit=False):
    data    = load_data()
    pending = load_pending()
    orders  = data.get("orders",[])
    revenue = sum(float(o.get("price",0)) for o in orders)
    total_s = sum(len(p.get("items",[])) for p in data["products"].values())

    stock_lines = []
    for p in data["products"].values():
        n   = len(p.get("items",[]))
        bar = stock_bar(n, 6)
        warn = "  ⚠️" if n < 3 else "  ✅" if n > 0 else "  ❌"
        stock_lines.append(f"  {p['name'][:14]:<14}  [{bar}]  {n}{warn}")
    stock_section = "\n".join(stock_lines) if stock_lines else "  Keine Produkte"

    text = (
        f"◈ {LINE_HEAVY} ◈\n"
        f"  ⚙️   ADMIN CONTROL PANEL\n"
        f"◈ {LINE_HEAVY} ◈\n\n"
        f"*📊  ÜBERSICHT*\n"
        + card([
            f"💎  Einnahmen:   `{revenue:.4f} LTC`",
            f"🧾  Verkäufe:    *{len(orders)}* gesamt",
            f"🕐  Wartend:     *{len(pending)}* offen",
            f"📦  Lager:       *{total_s}* Artikel",
        ]) +
        f"\n\n*📦  LAGERBESTAND*\n"
        f"{CORNER_TL}{LINE_LIGHT}{CORNER_TR}\n"
        f"{stock_section}\n"
        f"{CORNER_BL}{LINE_LIGHT}{CORNER_BR}"
    )

    keyboard = [
        [InlineKeyboardButton("➕  Produkt erstellen", callback_data="admin_add_product"),
         InlineKeyboardButton("📦  Lager auffüllen",  callback_data="admin_restock")],
        [InlineKeyboardButton("💳  LTC Adresse",       callback_data="admin_set_ltc"),
         InlineKeyboardButton("📋  Produktliste",      callback_data="admin_list")],
        [InlineKeyboardButton("📊  Statistiken",       callback_data="admin_stats"),
         InlineKeyboardButton("🔄  Refresh",           callback_data="admin_refresh")],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    if edit and hasattr(update,"callback_query") and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        msg = update.message or update.callback_query.message
        await msg.reply_text(text, reply_markup=markup, parse_mode="Markdown")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    action = query.data

    if action == "admin_set_ltc":
        await query.edit_message_text(
            f"{box('LTC ADRESSE', '💳')}\n\nSende deine Litecoin Empfangsadresse:",
            parse_mode="Markdown")
        return SET_LTC

    elif action == "admin_add_product":
        context.user_data["step"] = 1
        await query.edit_message_text(
            f"{box('NEUES PRODUKT  [1/4]', '➕')}\n\n📝  Wie soll das Produkt heißen?",
            parse_mode="Markdown")
        return ADD_NAME

    elif action == "admin_restock":
        data = load_data()
        if not data["products"]:
            await query.edit_message_text("❌  Keine Produkte vorhanden."); return ADMIN_MENU
        keyboard = []
        for pid, p in data["products"].items():
            n    = len(p.get("items",[]))
            bar  = stock_bar(n, 5)
            warn = "  ⚠️  LEER" if n == 0 else f"  ⚠️  NIEDRIG" if n < 3 else ""
            keyboard.append([InlineKeyboardButton(
                f"📦  {p['name']}  [{bar}] {n}{warn}",
                callback_data=f"restock_{pid}")])
        keyboard.append([InlineKeyboardButton("◂  Zurück", callback_data="admin_back")])
        await query.edit_message_text(
            f"{box('LAGER AUFFÜLLEN', '📦')}\n\nWelches Produkt soll aufgefüllt werden?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return RESTOCK_SELECT

    elif action == "admin_list":
        data = load_data()
        if not data["products"]:
            await query.edit_message_text("❌  Keine Produkte."); return ADMIN_MENU
        text = f"{box('PRODUKTLISTE', '📋')}\n\n"
        for i,(pid,p) in enumerate(data["products"].items(),1):
            n   = len(p.get("items",[]))
            bar = stock_bar(n)
            text += (
                f"*{i}.  {p['name']}*\n"
                f"   💎  `{p['price']} LTC`\n"
                f"   📊  `[{bar}]`  {n} Artikel\n"
                f"   📝  _{p.get('description','–')}_\n\n"
            )
        keyboard = [[InlineKeyboardButton("◂  Zurück", callback_data="admin_back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return ADMIN_MENU

    elif action in ("admin_stats","admin_refresh"):
        data    = load_data()
        pending = load_pending()
        orders  = data.get("orders",[])
        revenue = sum(float(o.get("price",0)) for o in orders)
        import datetime
        recent = orders[-5:][::-1]
        recent_lines = []
        for o in recent:
            ts = datetime.datetime.fromtimestamp(o.get("timestamp",0)).strftime("%d.%m  %H:%M")
            recent_lines.append(f"  {ts}  ·  {o['product']}  ·  {o['price']} LTC")
        if not recent_lines: recent_lines = ["  Noch keine Verkäufe"]

        text = (
            f"{box('STATISTIKEN', '📊')}\n\n"
            + card([
                f"💎  Einnahmen:   `{revenue:.6f} LTC`",
                f"🧾  Verkäufe:    *{len(orders)}*",
                f"🕐  Offen:       *{len(pending)}*",
                f"📦  Produkte:    *{len(data['products'])}*",
            ]) +
            f"\n\n*🕐  LETZTE VERKÄUFE*\n"
            f"{CORNER_TL}{LINE_LIGHT}{CORNER_TR}\n"
            + "\n".join(recent_lines) +
            f"\n{CORNER_BL}{LINE_LIGHT}{CORNER_BR}"
        )
        keyboard = [[InlineKeyboardButton("◂  Zurück", callback_data="admin_back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return ADMIN_MENU

    elif action == "admin_back":
        await show_admin_menu(update, context, edit=True)
        return ADMIN_MENU

    elif action.startswith("restock_"):
        pid = action.replace("restock_","")
        context.user_data["restock_pid"] = pid
        data = load_data()
        p    = data["products"][pid]
        n    = len(p.get("items",[]))
        bar  = stock_bar(n)
        await query.edit_message_text(
            f"{box(f'RESTOCK: {p['name'].upper()}', '📦')}\n\n"
            + card([f"📊  Aktuell:  `[{bar}]`  *{n}* Artikel"]) +
            f"\n\nSende die neuen Artikel – *einen pro Zeile*:\n\n"
            f"_Beispiel:_\n`KEY-XXXX-YYYY-ZZZZ\nKEY-AAAA-BBBB-CCCC`",
            parse_mode="Markdown")
        return RESTOCK_AMOUNT

async def set_ltc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ltc = update.message.text.strip()
    data = load_data(); data["ltc_address"] = ltc; save_data(data)
    await update.message.reply_text(
        f"{box('LTC ADRESSE GESETZT', '✅')}\n\n`{ltc}`", parse_mode="Markdown")
    await show_admin_menu(update, context); return ADMIN_MENU

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_product"] = {"name": update.message.text.strip(), "items": []}
    await update.message.reply_text(
        f"{box('NEUES PRODUKT  [2/4]', '➕')}\n\n📝  Beschreibe das Produkt:",
        parse_mode="Markdown"); return ADD_DESC

async def add_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_product"]["description"] = update.message.text.strip()
    await update.message.reply_text(
        f"{box('NEUES PRODUKT  [3/4]', '➕')}\n\n💎  Preis in LTC (z.B. `0.05`):",
        parse_mode="Markdown"); return ADD_PRICE

async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["new_product"]["price"] = float(update.message.text.strip())
        await update.message.reply_text(
            f"{box('NEUES PRODUKT  [4/4]', '➕')}\n\n📦  Füge die Artikel ein:\n_(einen pro Zeile)_",
            parse_mode="Markdown"); return ADD_STOCK
    except ValueError:
        await update.message.reply_text("❌  Ungültig. Nur Zahlen, z.B. `0.05`:", parse_mode="Markdown")
        return ADD_PRICE

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = [l.strip() for l in update.message.text.split("\n") if l.strip()]
    np    = context.user_data["new_product"]; np["items"] = items
    data  = load_data(); pid = str(int(time.time())); data["products"][pid] = np; save_data(data)
    bar   = stock_bar(len(items))
    await update.message.reply_text(
        f"{box('PRODUKT ERSTELLT', '✅')}\n\n"
        + card([
            f"📦  Name:     *{np['name']}*",
            f"💎  Preis:    `{np['price']} LTC`",
            f"📊  Lager:    `[{bar}]`  {len(items)} Artikel",
        ]), parse_mode="Markdown")
    await show_admin_menu(update, context); return ADMIN_MENU

async def restock_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid   = context.user_data.get("restock_pid")
    items = [l.strip() for l in update.message.text.split("\n") if l.strip()]
    data  = load_data()
    if pid in data["products"]:
        data["products"][pid]["items"].extend(items); save_data(data)
        p   = data["products"][pid]; n = len(p["items"]); bar = stock_bar(n)
        await update.message.reply_text(
            f"{box('RESTOCK ERFOLGREICH', '✅')}\n\n"
            + card([
                f"📦  {p['name']}",
                f"➕  Neu:      +{len(items)} Artikel",
                f"📊  Gesamt:   `[{bar}]`  *{n}* Artikel",
            ]), parse_mode="Markdown")
    else:
        await update.message.reply_text("❌  Produkt nicht gefunden.")
    await show_admin_menu(update, context); return ADMIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✗  Abgebrochen.  /admin oder /start")
    return ConversationHandler.END

# ── Main Loop ─────────────────────────────────────────────

def main():
    if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN nicht gesetzt!")
    if not ADMIN_IDS: raise RuntimeError("ADMIN_IDS nicht gesetzt!")

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin)],
        states={
            ADMIN_MENU:     [CallbackQueryHandler(admin_callback, pattern="^(admin_|restock_)")],
            SET_LTC:        [MessageHandler(filters.TEXT & ~filters.COMMAND, set_ltc)],
            ADD_NAME:       [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ADD_DESC:       [MessageHandler(filters.TEXT & ~filters.COMMAND, add_desc)],
            ADD_PRICE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)],
            ADD_STOCK:      [MessageHandler(filters.TEXT & ~filters.COMMAND, add_stock)],
            RESTOCK_SELECT: [CallbackQueryHandler(admin_callback, pattern="^(restock_|admin_)")],
            RESTOCK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, restock_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(show_product,  pattern="^product_"))
    app.add_handler(CallbackQueryHandler(buy_product,   pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(cancel_order,  pattern="^cancel_"))
    app.add_handler(CallbackQueryHandler(refresh_shop,  pattern="^refresh_shop$"))
    app.add_handler(CallbackQueryHandler(back_shop,     pattern="^back_shop$"))

    async def start_checker(app):
        asyncio.create_task(payment_checker_loop(app))
    app.post_init = start_checker

    print(f"◈ {LINE_HEAVY} ◈")
    print(f"  ✦  {SHOP_NAME} BOT AKTIV  ✦")
    print(f"◈ {LINE_HEAVY} ◈")
    app.run_polling()

if __name__ == "__main__":
    main()

import logging
import sqlite3
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# --- CONFIG ---
TOKEN = "DEIN_BOT_TOKEN"
ADMIN_ID = 12345678  # Deine ID

# --- DB SETUP (Erweitert für Wallets & Stock) ---
def init_db():
    conn = sqlite3.connect('shop.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT, price_usd REAL, content TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS orders (txid TEXT PRIMARY KEY, user_id INTEGER, amount REAL, status TEXT)')
    conn.commit()
    conn.close()

def get_wallet(crypto):
    conn = sqlite3.connect('shop.db')
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (f"wallet_{crypto}",))
    res = c.fetchone()
    conn.close()
    return res[0] if res else "Nicht gesetzt"

# --- KRYPTO LOGIK (Echtzeit API) ---
def get_crypto_price(symbol):
    try:
        res = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd").json()
        return res[symbol]['usd']
    except: return 0

async def check_payments(context: ContextTypes.DEFAULT_TYPE):
    """Dieser Loop läuft im Hintergrund und prüft alle offenen Zahlungen"""
    # Hier würde man eine Liste von erwarteten TXIDs prüfen. 
    # Da wir keine Payment-Gateway nutzen, müsste der User die TXID eingeben
    # oder der Bot scannt die Wallet nach dem Betrag.
    pass

# --- ADMIN COMMANDS ---
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    keyboard = [
        [InlineKeyboardButton("💰 Wallets setzen", callback_data="admin_wallets")],
        [InlineKeyboardButton("📦 Produkt hinzufügen", callback_data="admin_add_prod")]
    ]
    await update.message.reply_text("🦀 **MrKrabsyy Admin Panel**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# --- CORE LOGIK ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("🛒 Shop betreten", callback_data="view_shop")]]
    await update.message.reply_text("👋 Willkommen bei **MrKrabsyy Shop**\n\nZahlung: BTC, LTC, ETH, SOL, TON", 
                                  reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "admin_wallets":
        await query.message.reply_text("Sende mir die Wallets im Format:\n`SET LTC DEINE_ADRESSE`\n`SET BTC DEINE_ADRESSE`", parse_mode="Markdown")

    elif data == "view_shop":
        conn = sqlite3.connect('shop.db')
        prods = conn.execute("SELECT * FROM products").fetchall()
        if not prods:
            await query.edit_message_text("Shop ist aktuell leer.")
            return
        kb = [[InlineKeyboardButton(f"{p[1]} - ${p[2]}", callback_data=f"buy_{p[0]}")] for p in prods]
        await query.edit_message_text("Wähle ein Produkt:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("buy_"):
        pid = data.split("_")[1]
        # Krypto-Auswahl anzeigen...
        kb = [[InlineKeyboardButton("LTC", callback_data=f"pay_ltc_{pid}"), 
               InlineKeyboardButton("BTC", callback_data=f"pay_btc_{pid}")]]
        await query.edit_message_text("Womit möchtest du zahlen?", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("pay_"):
        _, coin, pid = data.split("_")
        address = get_wallet(coin.upper())
        
        # Beispiel für LTC Check (BlockCypher API)
        # Hier generiert der Bot die Info für den Kunden
        msg = (f"📥 **Zahlung einleiten**\n\n"
               f"Sende den Betrag an:\n`{address}`\n\n"
               f"Status: Warte auf Transaktion...\n"
               f"Bestätigungen: **0/4** (LTC Standard)")
        
        await query.edit_message_text(msg, parse_mode="Markdown")

# --- MESSAGE HANDLER FÜR ADMIN INPUT ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    text = update.message.text
    if text.startswith("SET "):
        parts = text.split(" ")
        coin = parts[1].upper()
        addr = parts[2]
        conn = sqlite3.connect('shop.db')
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (f"wallet_{coin}", addr))
        conn.commit()
        await update.message.reply_text(f"✅ Wallet für {coin} aktualisiert!")

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

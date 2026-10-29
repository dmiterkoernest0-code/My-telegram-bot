import os
import json
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters, ConversationHandler
)

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running"

@app.route('/health')
def health():
    return "OK"

TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

KEYS_FILE = "keys.json"
WAIT_RECEIPT = 0

# ---------- Товары (под PUBG) ----------
PRODUCTS = {
    "esp":  ("PUBG ESP (Wallhack)", "490 ₽"),
    "aim":  ("PUBG Aimbot",         "790 ₽"),
    "full": ("PUBG FULL (ESP+Aim)", "990 ₽"),
}

# ---------- Работа с ключами ----------
def load_keys():
    if not os.path.exists(KEYS_FILE):
        return {pid: [] for pid in PRODUCTS}
    with open(KEYS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for pid in PRODUCTS:
        data.setdefault(pid, [])
    return data

def save_keys(data):
    with open(KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def take_key(pid):
    data = load_keys()
    if data.get(pid):
        key = data[pid].pop(0)
        save_keys(data)
        return key
    return None

def add_keys(pid, keys):
    data = load_keys()
    data.setdefault(pid, []).extend(keys)
    save_keys(data)

# ---------- Пользовательская часть ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"{name} — {price}", callback_data=f"buy:{pid}")]
        for pid, (name, price) in PRODUCTS.items()
    ]
    await update.message.reply_text(
        "🔥 Добро пожаловать в магазин читов PUBG 🔥\n\n"
        "Выбери товар:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.split(":")[1]
    name, price = PRODUCTS[pid]
    context.user_data["product"] = (pid, name, price)
    await query.message.reply_text(
        f"Ты выбрал: *{name}* за *{price}*\n\n"
        f"💳 Оплати по реквизитам:\n"
        f"`0000 0000 0000 0000` (Сбербанк)\n"
        f"или USDT TRC-20: `TXXXXXXXXXXXXXXXXXXXX`\n\n"
        f"После оплаты пришли сюда **скриншот чека** 📸",
        parse_mode="Markdown"
    )
    return WAIT_RECEIPT

async def receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    pid, name, price = context.user_data.get("product", ("?", "?", "?"))

    keyboard = [[
        InlineKeyboardButton("✅ Подтвердить", callback_data=f"give:{user.id}:{pid}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"reject:{user.id}:{pid}"),
    ]]
    caption = (
        f"🧾 Новая заявка!\n"
        f"Пользователь: @{user.username or 'нет'} (ID: {user.id})\n"
        f"Товар: {name} — {price}"
    )
    if update.message.photo:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=update.message.photo[-1].file_id,
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=caption + f"\nСообщение: {update.message.text}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    await update.message.reply_text(
        "Заявка отправлена! Ожидай проверки — ключ придёт сюда ⏳"
    )
    return ConversationHandler.END

# ---------- Админская часть ----------

async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    action, user_id, pid = parts[0], int(parts[1]), parts[2]

    if action == "reject":
        try:
            await query.edit_message_caption(caption="❌ Заявка отклонена")
        except Exception:
            await query.edit_message_text("❌ Заявка отклонена")
        await context.bot.send_message(user_id, "❌ Оплата не подтверждена. Напиши в поддержку.")
        return

    # give
    key = take_key(pid)
    if not key:
        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ Ключи для товара «{PRODUCTS[pid][0]}» закончились!\n"
            f"Пополни список командой:\n"
            f"`/add {pid} КЛЮЧ1 КЛЮЧ2 КЛЮЧ3`",
            parse_mode="Markdown"
        )
        try:
            await query.edit_message_caption(caption="⚠️ Ключей нет — заявка ждёт")
        except Exception:
            pass
        return

    try:
        await query.edit_message_caption(caption="✅ Заявка подтверждена")
    except Exception:
        await query.edit_message_text("✅ Заявка подтверждена")

    await context.bot.send_message(
        user_id,
        f"🎉 Оплата подтверждена!\n\n"
        f"Товар: {PRODUCTS[pid][0]}\n"
        f"Твой ключ: `{key}`\n\n"
        f"Активация: зайди в личный кабинет и вставь ключ.",
        parse_mode="Markdown"
    )

    left = len(load_keys().get(pid, []))
    if left <= 2:
        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ Осталось ключей для «{PRODUCTS[pid][0]}»: {left}. Пора пополнить."
        )

# ---------- Админ: пополнение ключей ----------

async def add_keys_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Формат: `/add <товар> КЛЮЧ1 КЛЮЧ2 ...`\n"
            "Товары: " + ", ".join(PRODUCTS.keys()),
            parse_mode="Markdown"
        )
        return
    pid = context.args[0]
    if pid not in PRODUCTS:
        await update.message.reply_text(f"Нет такого товара. Есть: {', '.join(PRODUCTS.keys())}")
        return
    keys = context.args[1:]
    add_keys(pid, keys)
    await update.message.reply_text(
        f"✅ Добавлено {len(keys)} ключей для «{PRODUCTS[pid][0]}».\n"
        f"Всего: {len(load_keys()[pid])}"
    )

async def stock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    data = load_keys()
    lines = [f"• {PRODUCTS[pid][0]}: {len(data.get(pid, []))} шт." for pid in PRODUCTS]
    await update.message.reply_text("📦 Остатки:\n" + "\n".join(lines))

# ---------- Запуск ----------

def run_bot():
    application = Application.builder().token(TOKEN).build()

    user_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(buy, pattern="^buy:")],
        states={WAIT_RECEIPT: [MessageHandler(filters.ALL & ~filters.COMMAND, receive_receipt)]},
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_keys_cmd))
    application.add_handler(CommandHandler("stock", stock_cmd))
    application.add_handler(user_conv)
    application.add_handler(CallbackQueryHandler(admin_decision, pattern="^(give|reject):"))

    application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

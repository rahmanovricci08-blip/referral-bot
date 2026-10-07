import asyncio
import os
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not TOKEN:
    raise ValueError("BOT_TOKEN topilmadi! .env faylni tekshiring.")

bot = Bot(TOKEN)
dp = Dispatcher()

DB = "referral.db"


# =========================
# DATABASE
# =========================

def db():
    return sqlite3.connect(DB)


def create_database():
    conn = db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            referred_by INTEGER,
            referrals INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


def add_user(user_id, username, first_name, referred_by=None):

    conn = db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user_id,)
    )

    exists = cursor.fetchone()

    if exists:
        cursor.execute("""
            UPDATE users
            SET username = ?, first_name = ?
            WHERE user_id = ?
        """, (username or "", first_name or "", user_id))

        conn.commit()
        conn.close()
        return False

    valid_referrer = None

    if referred_by and referred_by != user_id:

        cursor.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (referred_by,)
        )

        if cursor.fetchone():
            valid_referrer = referred_by

    cursor.execute("""
        INSERT INTO users
        (user_id, username, first_name, referred_by, referrals)
        VALUES (?, ?, ?, ?, 0)
    """, (
        user_id,
        username or "",
        first_name or "",
        valid_referrer
    ))

    if valid_referrer:

        cursor.execute("""
            UPDATE users
            SET referrals = referrals + 1
            WHERE user_id = ?
        """, (valid_referrer,))

    conn.commit()
    conn.close()

    return True


def get_referrals(user_id):

    conn = db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT referrals FROM users WHERE user_id = ?",
        (user_id,)
    )

    result = cursor.fetchone()

    conn.close()

    return result[0] if result else 0


def get_total_users():

    conn = db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    result = cursor.fetchone()[0]

    conn.close()

    return result


def get_total_referrals():

    conn = db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COALESCE(SUM(referrals), 0) FROM users"
    )

    result = cursor.fetchone()[0]

    conn.close()

    return result


def get_rating():

    conn = db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT first_name, username, referrals
        FROM users
        ORDER BY referrals DESC
        LIMIT 10
    """)

    result = cursor.fetchall()

    conn.close()

    return result


# =========================
# MENU
# =========================

def menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🔗 Mening referral linkim",
                    callback_data="link"
                )
            ],

            [
                InlineKeyboardButton(
                    text="👥 Mening referralim",
                    callback_data="stats"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🏆 Reyting",
                    callback_data="rating"
                )
            ]

        ]
    )


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start(message: Message):

    referral_id = None

    parts = message.text.split()

    if len(parts) > 1 and parts[1].isdigit():

        referral_id = int(parts[1])

    new_user = add_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        referral_id
    )

    referrals = get_referrals(message.from_user.id)

    total = get_total_users()

    text = f"""
👋 <b>Salom, {message.from_user.first_name}!</b>

🎁 <b>Referral botga xush kelibsiz!</b>

👥 Sizning referral: <b>{referrals}</b>
👤 Jami foydalanuvchilar: <b>{total}</b>

👇 Quyidagi menyudan foydalaning.
"""

    if new_user and referral_id:

        text += "\n🎉 Siz referral orqali kirdingiz!"

    await message.answer(
        text,
        reply_markup=menu(),
        parse_mode="HTML"
    )


# =========================
# REFERRAL LINK
# =========================

@dp.callback_query(F.data == "link")
async def referral_link(callback: CallbackQuery):

    bot_info = await bot.get_me()

    link = f"https://t.me/{bot_info.username}?start={callback.from_user.id}"

    referrals = get_referrals(callback.from_user.id)

    text = f"""
🔗 <b>Sizning referral linkingiz:</b>

<code>{link}</code>

👥 Referral soningiz: <b>{referrals}</b>

📤 Linkni do'stlaringizga yuboring.
"""

    await callback.message.answer(
        text,
        parse_mode="HTML"
    )

    await callback.answer()


# =========================
# STATISTICS
# =========================

@dp.callback_query(F.data == "stats")
async def statistics(callback: CallbackQuery):

    referrals = get_referrals(callback.from_user.id)

    await callback.message.answer(
        f"""
📊 <b>Sizning statistikangiz</b>

👥 Taklif qilganlaringiz: <b>{referrals}</b>

🎯 Keyingi maqsad:
<b>{((referrals // 5) + 1) * 5}</b> ta referral
""",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================
# RATING
# =========================

@dp.callback_query(F.data == "rating")
async def rating(callback: CallbackQuery):

    users = get_rating()

    text = "🏆 <b>TOP 10 REFERRAL</b>\n\n"

    if not users:

        text += "Hali foydalanuvchilar yo'q."

    else:

        for i, user in enumerate(users, 1):

            first_name = user[0] or "User"
            username = user[1]
            referrals = user[2]

            name = f"@{username}" if username else first_name

            text += f"{i}. {name} — 👥 <b>{referrals}</b>\n"

    await callback.message.answer(
        text,
        parse_mode="HTML"
    )

    await callback.answer()


# =========================
# ADMIN
# =========================

@dp.message(Command("admin"))
async def admin(message: Message):

    if message.from_user.id != ADMIN_ID:

        await message.answer("⛔ Siz admin emassiz.")

        return

    total_users = get_total_users()
    total_referrals = get_total_referrals()

    await message.answer(
        f"""
🛠 <b>ADMIN PANEL</b>

👤 Jami foydalanuvchilar:
<b>{total_users}</b>

👥 Jami referral:
<b>{total_referrals}</b>
""",
        parse_mode="HTML"
    )


# =========================
# START BOT
# =========================

async def main():

    create_database()

    print("🤖 REFERRAL BOT ISHLAYAPTI!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
    
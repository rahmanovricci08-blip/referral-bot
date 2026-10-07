import asyncio
import os
import sqlite3
from contextlib import contextmanager
from urllib.parse import quote

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from dotenv import load_dotenv


# =========================================================
# SOZLAMALAR
# =========================================================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Savdodan 5% cashback
CASHBACK_PERCENT = 5.0

# Database
DB = "referral.db"


if not TOKEN:
    raise ValueError(
        "BOT_TOKEN topilmadi! .env yoki hosting Environment "
        "Variables ichida BOT_TOKEN ni kiriting."
    )

if ADMIN_ID == 0:
    raise ValueError(
        "ADMIN_ID topilmadi! .env yoki hosting Environment "
        "Variables ichida ADMIN_ID ni kiriting."
    )


bot = Bot(token=TOKEN)
dp = Dispatcher()


# =========================================================
# DATABASE
# =========================================================

@contextmanager
def get_db():

    conn = sqlite3.connect(
        DB,
        timeout=30,
        check_same_thread=False
    )

    try:

        conn.execute(
            "PRAGMA busy_timeout = 30000"
        )

        conn.execute(
            "PRAGMA journal_mode = WAL"
        )

        yield conn

        conn.commit()

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


def create_database():

    with get_db() as conn:

        cursor = conn.cursor()

        # Users
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                referred_by INTEGER,
                referrals INTEGER DEFAULT 0,
                cashback REAL DEFAULT 0
            )
        """)

        # Savdo so'rovlari
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                cashback REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Eski database bo'lsa cashback ustuni bo'lmasa qo'shamiz
        cursor.execute(
            "PRAGMA table_info(users)"
        )

        columns = [
            row[1]
            for row in cursor.fetchall()
        ]

        if "cashback" not in columns:

            cursor.execute(
                """
                ALTER TABLE users
                ADD COLUMN cashback REAL DEFAULT 0
                """
            )


# =========================================================
# USER
# =========================================================

def add_user(
    user_id: int,
    username: str | None,
    first_name: str | None,
    referred_by: int | None = None
):

    with get_db() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT user_id
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        exists = cursor.fetchone()

        # User mavjud
        if exists:

            cursor.execute(
                """
                UPDATE users
                SET username = ?,
                    first_name = ?
                WHERE user_id = ?
                """,
                (
                    username or "",
                    first_name or "",
                    user_id
                )
            )

            return False

        valid_referrer = None

        # Referralni tekshirish
        if (
            referred_by
            and referred_by != user_id
        ):

            cursor.execute(
                """
                SELECT user_id
                FROM users
                WHERE user_id = ?
                """,
                (referred_by,)
            )

            if cursor.fetchone():

                valid_referrer = referred_by

        # User yaratish
        cursor.execute(
            """
            INSERT INTO users (
                user_id,
                username,
                first_name,
                referred_by,
                referrals,
                cashback
            )
            VALUES (?, ?, ?, ?, 0, 0)
            """,
            (
                user_id,
                username or "",
                first_name or "",
                valid_referrer
            )
        )

        # Referralga +1
        if valid_referrer:

            cursor.execute(
                """
                UPDATE users
                SET referrals = referrals + 1
                WHERE user_id = ?
                """,
                (valid_referrer,)
            )

        return True


def get_user(user_id: int):

    with get_db() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                user_id,
                username,
                first_name,
                referred_by,
                referrals,
                cashback
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        return cursor.fetchone()


# =========================================================
# REFERRAL
# =========================================================

def get_referrals(user_id: int):

    user = get_user(user_id)

    if not user:
        return 0

    return user[4]


# =========================================================
# SAVDO SO'ROVI YARATISH
# =========================================================

def create_sale(
    user_id: int,
    amount: float
):

    cashback = (
        amount
        * CASHBACK_PERCENT
        / 100
    )

    with get_db() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO sales (
                user_id,
                amount,
                cashback,
                status
            )
            VALUES (?, ?, ?, 'pending')
            """,
            (
                user_id,
                amount,
                cashback
            )
        )

        return cursor.lastrowid, cashback


# =========================================================
# CASHBACK TASDIQLASH
# =========================================================

def approve_sale(sale_id: int):

    with get_db() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                user_id,
                amount,
                cashback,
                status
            FROM sales
            WHERE id = ?
            """,
            (sale_id,)
        )

        sale = cursor.fetchone()

        if not sale:
            return None

        user_id = sale[0]
        amount = sale[1]
        cashback = sale[2]
        status = sale[3]

        # Allaqachon tasdiqlangan
        if status != "pending":
            return None

        # Savdoni tasdiqlash
        cursor.execute(
            """
            UPDATE sales
            SET status = 'approved'
            WHERE id = ?
            """,
            (sale_id,)
        )

        # Cashback qo'shish
        cursor.execute(
            """
            UPDATE users
            SET cashback = cashback + ?
            WHERE user_id = ?
            """,
            (
                cashback,
                user_id
            )
        )

        cursor.execute(
            """
            SELECT cashback
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        result = cursor.fetchone()

        balance = result[0] if result else cashback

        return {
            "user_id": user_id,
            "amount": amount,
            "cashback": cashback,
            "balance": balance
        }


# =========================================================
# SAVDONI RAD ETISH
# =========================================================

def reject_sale(sale_id: int):

    with get_db() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                user_id,
                amount,
                cashback,
                status
            FROM sales
            WHERE id = ?
            """,
            (sale_id,)
        )

        sale = cursor.fetchone()

        if not sale:
            return None

        if sale[3] != "pending":
            return None

        cursor.execute(
            """
            UPDATE sales
            SET status = 'rejected'
            WHERE id = ?
            """,
            (sale_id,)
        )

        return {
            "user_id": sale[0],
            "amount": sale[1],
            "cashback": sale[2]
        }


# =========================================================
# PENDING SAVDOLAR
# =========================================================

def get_pending_sales():

    with get_db() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                sales.id,
                sales.user_id,
                sales.amount,
                sales.cashback,
                sales.created_at,
                users.username,
                users.first_name
            FROM sales
            LEFT JOIN users
                ON users.user_id = sales.user_id
            WHERE sales.status = 'pending'
            ORDER BY sales.id ASC
            """
        )

        return cursor.fetchall()


# =========================================================
# STATISTIKA
# =========================================================

def get_total_users():

    with get_db() as conn:

        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM users"
        )

        return cursor.fetchone()[0]


def get_total_referrals():

    with get_db() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT COALESCE(
                SUM(referrals),
                0
            )
            FROM users
            """
        )

        return cursor.fetchone()[0]


def get_total_cashback():

    with get_db() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT COALESCE(
                SUM(cashback),
                0
            )
            FROM users
            """
        )

        return cursor.fetchone()[0]


# =========================================================
# USER SAVDO REJIMI
# =========================================================

sale_waiting = set()


# =========================================================
# MENU
# =========================================================

def main_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="💰 Cashback",
                    callback_data="cashback"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🛒 Savdo",
                    callback_data="sale"
                )
            ],

            [
                InlineKeyboardButton(
                    text="👥 Referral",
                    callback_data="referral"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🔗 Referral link",
                    callback_data="link"
                )
            ]

        ]
    )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):

    referral_id = None

    parts = message.text.split()

    if len(parts) > 1:

        if parts[1].isdigit():

            referral_id = int(parts[1])

    new_user = add_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        referred_by=referral_id
    )

    user = get_user(
        message.from_user.id
    )

    referrals = user[4]
    cashback = user[5]

    text = f"""
👋 <b>Salom, {message.from_user.first_name}!</b>

🎁 <b>Referral + Cashback botga xush kelibsiz!</b>

👥 Referral: <b>{referrals} ta</b>

💰 Cashback:
<b>{cashback:,.0f} so‘m</b>

📈 Cashback foizi:
<b>{CASHBACK_PERCENT:g}%</b>

👇 Menyudan foydalaning.
"""

    if new_user and referral_id:

        text += """

🎉 Siz referral orqali qo‘shildingiz!
"""

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# =========================================================
# CASHBACK
# =========================================================

@dp.callback_query(F.data == "cashback")
async def cashback_button(
    callback: CallbackQuery
):

    user = get_user(
        callback.from_user.id
    )

    if not user:

        await callback.answer(
            "Avval /start bosing.",
            show_alert=True
        )

        return

    balance = user[5]

    text = f"""
💰 <b>CASHBACK BALANS</b>

💵 Sizning balansingiz:

<b>{balance:,.0f} so‘m</b>

📈 Cashback:

<b>{CASHBACK_PERCENT:g}%</b>

🛒 Savdo qiling va cashback yig‘ing.
"""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🛒 Savdo",
                    callback_data="sale"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🔙 Menyu",
                    callback_data="menu"
                )
            ]

        ]
    )

    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )

    await callback.answer()


# =========================================================
# SAVDO
# =========================================================

@dp.callback_query(F.data == "sale")
async def sale_button(
    callback: CallbackQuery
):

    sale_waiting.add(
        callback.from_user.id
    )

    await callback.message.answer(
        f"""
🛒 <b>SAVDO SUMMASI</b>

Savdo summasini so‘mda yuboring.

Masalan:

<code>100000</code>

📈 Cashback:
<b>{CASHBACK_PERCENT:g}%</b>

100 000 so‘mlik savdo uchun:

💰 <b>5 000 so‘m cashback</b>

⚠️ Cashback admin tasdiqlagandan keyin balansga tushadi.
""",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# SAVDO SUMMASINI QABUL QILISH
# =========================================================

@dp.message()
async def sale_amount(
    message: Message
):

    user_id = message.from_user.id

    if user_id not in sale_waiting:
        return

    sale_waiting.discard(user_id)

    if not message.text:
        return

    value = message.text.strip()

    value = value.replace(
        " ",
        ""
    )

    value = value.replace(
        ",",
        ""
    )

    try:

        amount = float(value)

    except ValueError:

        await message.answer(
            """
❌ <b>Noto‘g‘ri summa.</b>

Faqat raqam yuboring.

Masalan:

<code>100000</code>
""",
            parse_mode="HTML"
        )

        return

    if amount <= 0:

        await message.answer(
            "❌ Savdo summasi 0 dan katta bo‘lishi kerak."
        )

        return

    sale_id, cashback = create_sale(
        user_id,
        amount
    )

    await message.answer(
        f"""
✅ <b>SAVDO QABUL QILINDI</b>

🛒 Savdo:
<b>{amount:,.0f} so‘m</b>

💰 Cashback:
<b>+{cashback:,.0f} so‘m</b>

🆔 Savdo №:
<b>#{sale_id}</b>

⏳ Holat:
<b>Admin tasdig‘ini kutmoqda.</b>

Tasdiqlangandan keyin cashback
balansingizga qo‘shiladi.
""",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

    # Adminni xabardor qilish
    try:

        username = (
            f"@{message.from_user.username}"
            if message.from_user.username
            else "Username yo‘q"
        )

        admin_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[

                [
                    InlineKeyboardButton(
                        text="✅ Tasdiqlash",
                        callback_data=f"approve:{sale_id}"
                    ),

                    InlineKeyboardButton(
                        text="❌ Rad etish",
                        callback_data=f"reject:{sale_id}"
                    )
                ]

            ]
        )

        await bot.send_message(
            ADMIN_ID,
            f"""
🛒 <b>YANGI SAVDO</b>

🆔 Savdo:
<b>#{sale_id}</b>

👤 Foydalanuvchi:
<b>{message.from_user.first_name}</b>

🔹 ID:
<code>{user_id}</code>

🔹 Username:
<b>{username}</b>

💵 Savdo:
<b>{amount:,.0f} so‘m</b>

💰 Cashback:
<b>{cashback:,.0f} so‘m</b>
""",
            parse_mode="HTML",
            reply_markup=admin_keyboard
        )

    except Exception as e:

        print(
            "Admin xabarida xato:",
            e
        )


# =========================================================
# REFERRAL
# =========================================================

@dp.callback_query(F.data == "referral")
async def referral_button(
    callback: CallbackQuery
):

    user = get_user(
        callback.from_user.id
    )

    if not user:

        await callback.answer(
            "Avval /start bosing.",
            show_alert=True
        )

        return

    referrals = user[4]

    text = f"""
👥 <b>REFERRAL</b>

Siz taklif qilganlar:

<b>{referrals} ta</b>

Do‘stlaringizni referral
linkingiz orqali taklif qiling.
"""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🔗 Referral link",
                    callback_data="link"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🔙 Menyu",
                    callback_data="menu"
                )
            ]

        ]
    )

    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )

    await callback.answer()


# =========================================================
# REFERRAL LINK
# =========================================================

@dp.callback_query(F.data == "link")
async def referral_link(
    callback: CallbackQuery
):

    bot_info = await bot.get_me()

    link = (
        f"https://t.me/"
        f"{bot_info.username}"
        f"?start="
        f"{callback.from_user.id}"
    )

    share_url = (
        "https://t.me/share/url"
        f"?url={quote(link)}"
        f"&text={quote('🎁 Botga qo‘shiling!')}"
    )

    referrals = get_referrals(
        callback.from_user.id
    )

    text = f"""
🔗 <b>REFERRAL LINK</b>

<code>{link}</code>

👥 Referral:
<b>{referrals} ta</b>

📤 Do‘stlaringizga yuboring.
"""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="📤 Ulashish",
                    url=share_url
                )
            ],

            [
                InlineKeyboardButton(
                    text="🔙 Menyu",
                    callback_data="menu"
                )
            ]

        ]
    )

    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )

    await callback.answer()


# =========================================================
# MENU
# =========================================================

@dp.callback_query(F.data == "menu")
async def menu_button(
    callback: CallbackQuery
):

    await callback.message.answer(
        "🏠 <b>ASOSIY MENYU</b>",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# ADMIN TEKSHIRISH
# =========================================================

def is_admin(user_id: int):

    return user_id == ADMIN_ID


# =========================================================
# ADMIN PANEL
# =========================================================

@dp.message(Command("admin"))
async def admin_panel(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "⛔ Siz admin emassiz."
        )

        return

    total_users = get_total_users()
    total_referrals = get_total_referrals()
    total_cashback = get_total_cashback()
    pending = get_pending_sales()

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🛒 Kutilayotgan savdolar",
                    callback_data="pending_sales"
                )
            ]

        ]
    )

    await message.answer(
        f"""
👨‍💼 <b>ADMIN PANEL</b>

👤 Foydalanuvchilar:
<b>{total_users}</b>

👥 Jami referral:
<b>{total_referrals}</b>

💰 Berilgan cashback:
<b>{total_cashback:,.0f} so‘m</b>

⏳ Kutilayotgan savdolar:
<b>{len(pending)}</b>
""",
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# PENDING SAVDOLAR
# =========================================================

@dp.callback_query(F.data == "pending_sales")
async def pending_sales(
    callback: CallbackQuery
):

    if not is_admin(
        callback.from_user.id
    ):

        await callback.answer(
            "⛔ Ruxsat yo‘q.",
            show_alert=True
        )

        return

    sales = get_pending_sales()

    if not sales:

        await callback.message.answer(
            "⏳ Hozir kutilayotgan savdolar yo‘q."
        )

        await callback.answer()

        return

    await callback.message.answer(
        f"⏳ <b>KUTILAYOTGAN SAVDOLAR: {len(sales)}</b>",
        parse_mode="HTML"
    )

    for sale in sales:

        (
            sale_id,
            user_id,
            amount,
            cashback,
            created_at,
            username,
            first_name
        ) = sale

        name = first_name or "User"

        if username:

            name += f" (@{username})"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[

                [
                    InlineKeyboardButton(
                        text="✅ Tasdiqlash",
                        callback_data=f"approve:{sale_id}"
                    ),

                    InlineKeyboardButton(
                        text="❌ Rad etish",
                        callback_data=f"reject:{sale_id}"
                    )
                ]

            ]
        )

        await callback.message.answer(
            f"""
🛒 <b>Savdo #{sale_id}</b>

👤 {name}

🆔 ID:
<code>{user_id}</code>

💵 Savdo:
<b>{amount:,.0f} so‘m</b>

💰 Cashback:
<b>{cashback:,.0f} so‘m</b>

🕐 {created_at}
""",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    await callback.answer()


# =========================================================
# ADMIN TASDIQLASH
# =========================================================

@dp.callback_query(F.data.startswith("approve:"))
async def approve_callback(
    callback: CallbackQuery
):

    if not is_admin(
        callback.from_user.id
    ):

        await callback.answer(
            "⛔ Ruxsat yo‘q.",
            show_alert=True
        )

        return

    sale_id = int(
        callback.data.split(":")[1]
    )

    result = approve_sale(
        sale_id
    )

    if not result:

        await callback.answer(
            "❌ Bu savdo allaqachon ko‘rib chiqilgan.",
            show_alert=True
        )

        return

    user_id = result["user_id"]
    amount = result["amount"]
    cashback = result["cashback"]
    balance = result["balance"]

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    await callback.message.answer(
        f"""
✅ <b>SAVDO TASDIQLANDI</b>

🆔 Savdo:
<b>#{sale_id}</b>

💵 Savdo:
<b>{amount:,.0f} so‘m</b>

💰 Cashback:
<b>+{cashback:,.0f} so‘m</b>

👤 User ID:
<code>{user_id}</code>

💵 Yangi balans:
<b>{balance:,.0f} so‘m</b>
""",
        parse_mode="HTML"
    )

    # Userga xabar
    try:

        await bot.send_message(
            user_id,
            f"""
🎉 <b>SAVDONGIZ TASDIQLANDI!</b>

🆔 Savdo:
<b>#{sale_id}</b>

💵 Savdo:
<b>{amount:,.0f} so‘m</b>

💰 Cashback:
<b>+{cashback:,.0f} so‘m</b>

💵 Cashback balansingiz:
<b>{balance:,.0f} so‘m</b>
""",
            parse_mode="HTML"
        )

    except Exception as e:

        print(
            "Userga xabar yuborishda xato:",
            e
        )

    await callback.answer(
        "✅ Savdo tasdiqlandi!"
    )


# =========================================================
# ADMIN RAD ETISH
# =========================================================

@dp.callback_query(F.data.startswith("reject:"))
async def reject_callback(
    callback: CallbackQuery
):

    if not is_admin(
        callback.from_user.id
    ):

        await callback.answer(
            "⛔ Ruxsat yo‘q.",
            show_alert=True
        )

        return

    sale_id = int(
        callback.data.split(":")[1]
    )

    result = reject_sale(
        sale_id
    )

    if not result:

        await callback.answer(
            "❌ Bu savdo allaqachon ko‘rib chiqilgan.",
            show_alert=True
        )

        return

    user_id = result["user_id"]
    amount = result["amount"]

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    await callback.message.answer(
        f"""
❌ <b>SAVDO RAD ETILDI</b>

🆔 Savdo:
<b>#{sale_id}</b>

👤 User ID:
<code>{user_id}</code>

💵 Savdo:
<b>{amount:,.0f} so‘m</b>
""",
        parse_mode="HTML"
    )

    # Userga xabar
    try:

        await bot.send_message(
            user_id,
            f"""
❌ <b>SAVDO RAD ETILDI</b>

🆔 Savdo:
<b>#{sale_id}</b>

💵 Savdo:
<b>{amount:,.0f} so‘m</b>

Agar xatolik bo‘lsa,
admin bilan bog‘laning.
""",
            parse_mode="HTML"
        )

    except Exception as e:

        print(
            "Userga xabar yuborishda xato:",
            e
        )

    await callback.answer(
        "❌ Savdo rad etildi."
    )


# =========================================================
# BOTNI ISHGA TUSHIRISH
# =========================================================

async def main():

    create_database()

    print("==============================")
    print("🤖 BOT ISHLAYAPTI")
    print("==============================")
    print(
        f"💰 Cashback: "
        f"{CASHBACK_PERCENT:g}%"
    )
    print(
        f"👨‍💼 Admin ID: "
        f"{ADMIN_ID}"
    )

    await dp.start_polling(bot)


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "🛑 Bot to‘xtatildi."
        )

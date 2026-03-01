# -*- coding: utf-8 -*-@dp.pre_checkout_query()
import asyncio
import sqlite3
import logging
import random
import pytz
import aiosqlite
import socketio
import json
import re
import websockets
import datetime as dt_module
import os
from dotenv import load_dotenv

from datetime import datetime, timedelta
from aiogram_sqlite_storage.sqlitestore import SQLStorage
from groq import Groq
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.types import ReplyKeyboardRemove
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto  # Добавь это
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.chat_action import ChatActionSender

from aiogram import F, types
from aiogram.types import LabeledPrice, PreCheckoutQuery
load_dotenv()

# --- КОНФИГУРАЦИЯ ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))
DONATION_URL = os.getenv("DONATION_URL")
CARD_DETAILS = os.getenv("CARD_DETAILS")
DA_WIDGET_TOKEN = os.getenv("DA_WIDGET_TOKEN")

waiting_girls = [] # Список ID девушек, которые ищут общение
scheduler = AsyncIOScheduler()

# --- АГЕНТСТВО ПАРНЕЙ ---
GUYS_MODERATORS = {
    "Матвей 19 лет": 743,
    "Мафия 18": 7752,
    "Марк 25 лет": ADMIN_ID, 
    "Саня 17": 64470,
    "Кларк 20": 5884
}
client = Groq(api_key=GROQ_API_KEY)
MODEL_ID = "llama-3.1-8b-instant"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot_errors.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

bot = Bot(token=TELEGRAM_TOKEN)
# --- БЛОК ХРАНИЛИЩА (Заменяет старый dp = Dispatcher()) ---
# Стало (ПРАВИЛЬНО):
storage = SQLStorage("fsm_states.db")
dp = Dispatcher(storage=storage)
# --- ТВОИ ПЕРЕМЕННЫЕ ---
RANDOM_NAMES = ["Марк", "Алекс", "Дамир", "Лиам", "Артур", "Макс", "Кристиан", "Эрик"]
RANDOM_STYLES = ["Дерзкий, но заботливый", "Романтичный и нежный", "Уверенный и харизматичный", "Спокойный и понимающий"]
RANDOM_HOBBIES = ["Путешествия и спорт", "Музыка и кино", "Чтение и саморазвитие", "Автомобили и экстрим"]

# --- БАЗА ДАННЫХ ---
DB_PATH = 'mark_empire_final.db'
# Ожидаю следующую часть: Классы состояний (FSM), Middleware и основные клавиатуры (main_kb).
# --- СОСТОЯНИЯ (FSM) ---
class RegStates(StatesGroup):
    bot_name = State()
    bot_style = State()
    bot_hobby = State()
    user_name = State()
    user_age = State()

class CapsuleStates(StatesGroup):
    waiting_for_content = State()
    waiting_for_date = State()

class DiaryStates(StatesGroup): 
    setting_pass = State()
    entering_pass = State()
    active = State()

class GuyRegStates(StatesGroup):
    wait_name = State()
    wait_age = State()
    confirm = State()

class EditProfileStates(StatesGroup):
    wait_new_user_name = State()
    wait_new_bot_name = State()
class DragonStates(StatesGroup):
    naming = State()

class GiftStates(StatesGroup):
    waiting_for_receiver = State() # Ожидаем ID или имя подруги
    waiting_for_amount = State()   # Ожидаем сумму XP

class ExtraStates(StatesGroup):
    write_admin = State()      # Чат с админом/парнем
    live_chat = State()        # Прямой эфир
    rate_look = State()        # Оценка образа
    friend_chat = State()      # Анонимный чат подружек
    contest_confirm = State()  # Подтверждение участия в конкурсе
    write_anon = State()       # Написание анонимки
    gossip_mode = State()      # Чат сплетен
    loyalty_test = State()     # Проверка верности (Детектор лжи)
    tiktok_story = State()     # <--- Твоя новая кнопка для сбора контента

class AdminStates(StatesGroup):
    broadcast_msg = State()
    manage_user_id = State()
    waiting_for_voice = State()  # <--- ДОБАВЬ ЭТУ СТРОКУ


class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = None
        if isinstance(event, types.Message):
            user_id = event.chat.id
        elif isinstance(event, types.CallbackQuery):
            user_id = event.message.chat.id

        if user_id:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,)) as cursor:
                    is_banned = await cursor.fetchone()
            
            if is_banned:
                if isinstance(event, types.CallbackQuery):
                    await event.answer("🚫 Доступ заблокирован.", show_alert=True)
                return 

        return await handler(event, data)
class CompatibilityStates(StatesGroup):
    wait_user_bday = State()
    wait_partner_name = State()
    wait_partner_bday = State()
# Класс состояний (добавь к остальным в начале кода)
class GuyTest(StatesGroup):
    answering = State()

# --- MIDDLEWARE АКТИВНОСТИ ---
async def auto_clean_inactive_chats():
    # Получаем текущее время в Алматы для сравнения
    now_kz = datetime.now(pytz.utc) + timedelta(hours=5)
    # Вычисляем порог (1 час назад)
    one_hour_ago = (now_kz - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"⏰ [DEBUG] Проверка неактивности. Ищу чаты, заброшенные до {one_hour_ago}")
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT guy_id, user_id FROM moderator_status WHERE is_busy = 1 AND last_activity < ?", 
            (one_hour_ago,)
        ) as cursor:
            inactive = await cursor.fetchall()
            
        if not inactive:
            print("✅ Активных зависших чатов не найдено.")
            return

        for g_id, u_id in inactive:
            await db.execute("UPDATE moderator_status SET is_busy = 0, user_id = NULL WHERE guy_id = ?", (g_id,))
            try:
                # Сброс FSM
                u_ctx = dp.fsm.resolve_context(bot, chat_id=u_id, user_id=u_id)
                await u_ctx.clear()
                g_ctx = dp.fsm.resolve_context(bot, chat_id=g_id, user_id=g_id)
                await g_ctx.clear()
                
                # Уведомления
                kb_u = await main_kb(u_id)
                await bot.send_message(u_id, "⌛️ **Чат закрыт.**\nДиалог завершен автоматически из-за долгого отсутствия сообщений.", reply_markup=kb_u)
                await bot.send_message(g_id, f"⌛️ Чат с юзером {u_id} закрыт по таймеру.")
            except: 
                pass
            
        await db.commit()
        print(f"🧹 Авто-чистка: закрыто {len(inactive)} чатов.")

async def send_puzzle_gallery_item(message: Message, index: int, total_opened: int):
    photo_id = MARK_PUZZLE_IDS[index]
    nav_btns = []
    if index > 0:
        nav_btns.append(InlineKeyboardButton(text="⬅️", callback_data=f"puzzle_nav_{index-1}"))
    if index < total_opened - 1:
        nav_btns.append(InlineKeyboardButton(text="➡️", callback_data=f"puzzle_nav_{index+1}"))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        nav_btns,
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")]
    ])
    caption = f"🖼 **Твоя коллекция**\nКусочек {index + 1} из {total_opened} открытых."

    try:
        await message.edit_media(
            media=InputMediaPhoto(media=photo_id, caption=caption, parse_mode="Markdown"),
            reply_markup=kb
        )
    except Exception:
        await message.answer_photo(photo=photo_id, caption=caption, reply_markup=kb, parse_mode="Markdown")

class ActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = None
        if isinstance(event, types.Message):
            user_id = event.chat.id
        elif isinstance(event, types.CallbackQuery) and event.message:
            user_id = event.message.chat.id

        if user_id:
            try:
                kz_time = (datetime.now(pytz.utc) + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
                today = (datetime.now(pytz.utc) + timedelta(hours=5)).strftime("%Y-%m-%d")
                
                async with aiosqlite.connect(DB_PATH) as db:
                    # ОБНОВЛЯЕМ время захода
                    await db.execute("UPDATE users SET last_seen = ? WHERE user_id = ?", (kz_time, user_id))
                    # ЗАПИСЫВАЕМ активность для отчета (теперь внутри with)
                    await db.execute("INSERT OR IGNORE INTO user_stats_daily (user_id, date) VALUES (?, ?)", (user_id, today))
                    await db.commit()
            except Exception as e:
                logging.error(f"Ошибка Middleware: {e}")

        return await handler(event, data)
FEATURES_TO_CHECK = [
    "🎁 ТАЙНАЯ СУМКА", "Твоя тайна в TIKTOK🤫", # <-- Добавили сюда
    "📔 Секретный дневник", "💌 Капсула времени", "🔥 Горячий Марк", 
    "👗 Оцени мой образ", "👑 Голосование", "👯‍♀️ Найти подружку",
    "📊 Рейтинг пар", "🙋‍♂️ Реальный парень", "🌟 VIP & Подруги", 
    "✍️ Написать админу", "🫦 18+ Сокровенное", "👤 Профиль", 
    "👯‍♀️ Сплетни", "😔 Нет настроения", 
    "✉️ Мои анонимки", "🕵️ Проверка верности", "🌌 Совместимость",
    "🐲 Наш Дракон"
]

MENU_BUTTONS = [
    "🎁 ТАЙНАЯ СУМКА", "Твоя тайна в TIKTOK🤫", # <-- И сюда тоже
    "📔 Секретный дневник", "💌 Капсула времени", 
    "🔥 Горячий Марк", "👗 Оцени мой образ", 
    "👑 Голосование", "👯‍♀️ Найти подружку",
    "📊 Рейтинг пар", "🙋‍♂️ Реальный парень", 
    "🌟 VIP & Подруги", "✍️ Написать админу", 
    "🫦 18+ Сокровенное", "👤 Профиль", "👯‍♀️ Сплетни",
    "😔 Нет настроения", "✉️ Мои анонимки",
    "🕵️ Проверка верности", "🌌 Совместимость",
    "🐲 Наш Дракон"
]
async def main_kb(user_id=None):
    # 1. Считаем подружек в очереди
    count = len(waiting_girls)
    friend_btn_text = f"👯‍♀️ Подружка ({count} ждёт) 🔥" if count > 0 else "👯‍♀️ Найти подружку"

    # 2. Получаем счетчик сплетен
    g_count = 0
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT new_gossips_count FROM users WHERE user_id = ?", (user_id,)) as cursor:
                res = await cursor.fetchone()
                if res and res[0] is not None:
                    g_count = res[0]
    except Exception as e:
        logging.error(f"Ошибка получения счетчика сплетен: {e}")

    # 3. Формируем текст кнопок
    diary_btn_text = "📔 Секретный дневник"
    gossip_btn_text = f"👯‍♀️ Сплетни (+{g_count})" if g_count > 0 else "👯‍♀️ Сплетни"
    
    # ФОРМИРУЕМ СПИСОК КНОПОК
    kb_list = [
        [KeyboardButton(text="🎁 ТАЙНАЯ СУМКА"), KeyboardButton(text="Твоя тайна в TIKTOK🤫")], # <-- ВОТ ОНА, ПЕРВАЯ КНОПКА
        [KeyboardButton(text=diary_btn_text), KeyboardButton(text="💌 Капсула времени")],
        [KeyboardButton(text="👗 Оцени мой образ"), KeyboardButton(text="👑 Голосование")],
        [KeyboardButton(text="📊 Рейтинг пар"), KeyboardButton(text=friend_btn_text)],
        [KeyboardButton(text=gossip_btn_text), KeyboardButton(text=" 🔥 Горячий Марк")], 
        [KeyboardButton(text="😔 Нет настроения"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="🙋‍♂️ Реальный парень"), KeyboardButton(text="🌟 VIP & Подруги")],
        [KeyboardButton(text="✉️ Мои анонимки"), KeyboardButton(text="✍️ Написать админу")],
        [KeyboardButton(text="🫦 18+ Сокровенное"), KeyboardButton(text="🕵️ Проверка верности")],
        [KeyboardButton(text="🌌 Совместимость"), KeyboardButton(text="🐲 Наш Дракон")]
    ]   
    return ReplyKeyboardMarkup(keyboard=kb_list, resize_keyboard=True)

def profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить моё имя", callback_data="edit_user_name")],
        [InlineKeyboardButton(text="🤖 Изменить имя парня", callback_data="edit_bot_name")],
        [InlineKeyboardButton(text="💎 Купить VIP / Подруги", callback_data="go_to_vip_section")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])

def diary_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📖 Читать"), KeyboardButton(text="🚪 Выйти")]], resize_keyboard=True)

def stop_chat_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Завершить диалог")]], resize_keyboard=True)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def get_log_setting():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key='log_all'") as cursor:
            res = await cursor.fetchone()
    return res[0] if res else 1

async def check_guy_response(user_id: int, guy_id: int):
    """Проверяет, ответил ли парень за 10 минут."""
    # Получаем контекст девушки
    state_ctx = dp.fsm.resolve_context(bot, chat_id=user_id, user_id=user_id)
    data = await state_ctx.get_data()
    current_state = await state_ctx.get_state()

    # Проверяем: в чате ли еще девушка и не было ли ответа
    # ВАЖНО: убедись, что при первом ответе парня ты делаешь: 
    # await state.update_data(was_answered=True)
    
    is_in_chat = current_state == ExtraStates.live_chat.state or current_state == "ExtraStates:live_chat"
    
    if is_in_chat and data.get("target") == guy_id and not data.get("was_answered"):
        
        async with aiosqlite.connect(DB_PATH) as db:
            # 1. Возвращаем попытку девушке
            await db.execute("UPDATE users SET tries_chat = tries_chat + 1 WHERE user_id = ?", (user_id,))
            # 2. ШТРАФ: Выключаем парню Онлайн и Занят
            await db.execute("UPDATE moderator_status SET is_online = 0, is_busy = 0 WHERE guy_id = ?", (guy_id,))
            await db.commit()

        # 3. Очищаем стейт девушки и шлем меню
        await state_ctx.clear()
        kb = await main_kb(user_id)
        try:
            await bot.send_message(
                user_id, 
                "😔 **Парень не ответил...**\n\nЯ вернул тебе попытку. Похоже, он сейчас занят. Попробуй выбрать другого! ✨",
                reply_markup=kb,
                parse_mode="Markdown"
            )
        except: pass

        # 4. Уведомляем и сбрасываем парня
        try:
            p_state = dp.fsm.resolve_context(bot, chat_id=guy_id, user_id=guy_id)
            await p_state.clear()
            await bot.send_message(
                guy_id, 
                "🔔 **ТЫ ВЫШЕЛ ИЗ ОНЛАЙНА**\n\nТы пропустил диалог (10 мин без ответа). Нажми /online, когда будешь готов работать! 💔"
            )
        except: pass

    # ВСЕГДА удаляем задачу в конце, чтобы не дублировалась
    try:
        scheduler.remove_job(f"wait_reply_{user_id}")
    except:
        pass
async def toggle_log_setting():
    current = await get_log_setting()
    new_val = 0 if current == 1 else 1
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE settings SET value=? WHERE key='log_all'", (new_val,))
        await db.commit()
    return new_val

async def get_user(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?", (uid,)) as cursor:
            user = await cursor.fetchone()
    
    if not user:
        return None

    # Индексы: 2 - is_vip (1/0), 3 - vip_until (дата)
    is_vip = user[2]
    vip_until = user[3]

    if is_vip == 1 and vip_until:
        try:
            # Превращаем строку из базы в объект времени
            # Добавим обработку разных форматов на всякий случай
            if len(vip_until) > 10:
                vip_until_dt = datetime.strptime(vip_until, "%Y-%m-%d %H:%M:%S")
            else:
                vip_until_dt = datetime.strptime(vip_until, "%Y-%m-%d")

            # СРАВНИВАЕМ: если текущее время больше даты в базе — VIP ВЫШЕЛ
            if datetime.now() > vip_until_dt:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("UPDATE users SET is_vip = 0, vip_until = NULL WHERE user_id = ?", (uid,))
                    await db.commit()
                
                # Обновляем данные в текущей переменной, чтобы бот сразу знал, что VIP нет
                user_list = list(user)
                user_list[2] = 0
                user_list[3] = None
                user = tuple(user_list)
                logging.info(f"👑 VIP-статус у {uid} истек и был аннулирован автоматически.")
        except Exception as e:
            logging.error(f"Ошибка парсинга даты VIP для {uid}: {e}")
            
    return user
async def get_detailed_user_info(user_id, tg_user, tag_name, original_text=""):
    u = await get_user(user_id)
    db_name = u[1] if u and u[1] else "Не указано"
    # Индекс возраста в твоей БД обычно u[13] или u[15], проверь (в r5_age ты ставишь u_age)
    # Предположим, возраст идет после имени или в конце. Если в БД есть u_age:
    try:
        age = u[4] if u[4] else "Не указан" # Поправь индекс под свою БД если надо
    except:
        age = "Не указан"
        
    bot_name = u[5] if u and u[5] else "Марк"
    tg_username = f"@{tg_user.username}" if tg_user.username else "скрыт"
    user_link = f"https://t.me/{tg_user.username}" if tg_user.username else f"tg://user?id={user_id}"

    return (
        f"<b>{tag_name}</b>\n\n"
        f"👤 <b>Имя:</b> {db_name}\n"
        f"🎂 <b>Возраст:</b> {age}\n"
        f"📱 <b>Telegram:</b> {tg_user.full_name} ({tg_username})\n"
        f"📝 <b>Оригинал текста:</b> <i>{original_text}</i>\n"
        f"🤖 <b>Бот:</b> {bot_name}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"🔗 <a href='{user_link}'>ОТКРЫТЬ ПРОФИЛЬ</a>"
    )

async def check_user_or_reg(m: types.Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT u_name FROM users WHERE user_id=?", (m.chat.id,)) as cursor:
            u = await cursor.fetchone()
    
    if u is None or u[0] is None or u[0] == "":
        await state.clear()
        
        bn = "Марк"
        bs = "Романтик"
        
        # Исправленный запрос: 7 колонок - 7 значений
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT OR IGNORE INTO users 
                   (user_id, is_vip, tries_chat, tries_look, xp, last_seen, reg_date) 
                   VALUES (?, 0, 3, 3, 500, ?, ?)""", 
                (
                    m.chat.id, 
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                    datetime.now().strftime("%Y-%m-%d")
                )
            )
            await db.commit()
        
        await m.answer(
            f"Привет! ✨\nДавай знакомиться. Я твой идеальный спутник:\n\n"
            f"👤 Имя: <b>{bn}</b>\n"
            f"🎭 Характер: <b>{bs}</b>\n\n"
            "Напиши, пожалуйста, <b>как мне тебя называть?</b> (Твое имя)",
            reply_markup=types.ReplyKeyboardRemove(),
            parse_mode="HTML"
        )
        
        await state.set_state(RegStates.user_name)
        return False 
        
    return True

# --- КОМАНДЫ АДМИНИСТРАТОРА ---
def calculate_numerology(date_str):
    # Складываем все цифры даты до получения однозначного числа
    nums = [int(d) for d in date_str if d.isdigit()]
    total = sum(nums)
    while total > 9:
        total = sum(int(digit) for digit in str(total))
    return total
# Класс состояний (добавь к остальным в начале кода)

@dp.message(F.successful_payment)
async def success_payment_handler(m: Message):
    user_id = m.from_user.id
    payload = m.successful_payment.invoice_payload
    # Ссылка на профиль для админа
    user_link = f"<a href='tg://user?id={user_id}'>{m.from_user.full_name}</a>"
    
    async with aiosqlite.connect(DB_PATH) as db:
        # --- 1. ЛОГИКА ГОРЯЧИХ ФОТО (hot_...) ---
        if payload.startswith("hot_"):
            content_type = payload.replace("hot_", "")
            
            if content_type == "part":
                file_id = "AgACAgIAAxkBAAEBOiRpmCebSVwMigyhYs9mNjHAVyvZBgACThRrGwV7wEiC-2ml4n3cfgEAAwIAA20AAzoE"
                caption = "Твой секретный кусочек... 🔥 Как тебе мой торс?"
                await db.execute("UPDATE users SET puzzle_step = puzzle_step + 1 WHERE user_id = ?", (user_id,))
            
            elif content_type == "bottom":
                file_id = "AgACAgIAAxkBAAEBOiZpmCfjbtL5T7JIxkhj12seQ0ExsAACUhRrGwV7wEgdHTz_NwgZYAEAAwIAA20AAzoE"
                caption = "Только для твоих глаз... 😏 Почти всё самое интересное."
                
            elif content_type == "full":
                file_id = "AgACAgIAAxkBAAEBOihpmCgHXaV_gxg7oBjdcrUtDTv_qgACVRRrGwV7wEh3ywwQLvRvGwEAAwIAA3gAAzoE"
                caption = "Я весь твой. Каждая клеточка... ❤️\n\n🌟 **Бонус:** Тебе открыт VIP-доступ навсегда!"
                await db.execute("UPDATE users SET is_vip = 1, vip_until = NULL, bought_full = 1 WHERE user_id = ?", (user_id,))
                await db.commit()
                await bot.send_photo(user_id, photo=file_id, caption=caption, parse_mode="HTML")
                await m.answer("✨ **Поздравляю!** Теперь тебе доступны все VIP-функции бота.")
                # Уведомление админу ПЕРЕД выходом
                await bot.send_message(ADMIN_ID, f"🔥 <b>ПОЛНЫЙ ПАК ФОТО + ВЕЧНЫЙ VIP!</b>\nЮзер: {user_link}\nID: <code>{user_id}</code>", parse_mode="HTML")
                return 

            await db.commit()
            await bot.send_photo(user_id, photo=file_id, caption=caption)
            await bot.send_message(ADMIN_ID, f"🔥 <b>ПРОДАЖА ФОТО!</b>\nЮзер: {user_link}\nТип: {content_type}\nID: <code>{user_id}</code>", parse_mode="HTML")

        # --- 2. ЛОГИКА ТАЙНОЙ СУМКИ (lootbox) ---
        elif payload == "lootbox_stars_payment":
            from datetime import datetime, timedelta
            rarity, prize_text = await get_lootbox_prize()
            
            xp_to_add = 5000
            if "50,000" in prize_text: xp_to_add = 50000
            elif "10,000" in prize_text: xp_to_add = 10000
            
            days = 1
            if rarity == "LEGENDARY": days = 30
            elif rarity == "RARE": days = 7
            
            until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            await db.execute("UPDATE users SET is_vip=1, vip_until=?, xp=xp+? WHERE user_id=?", (until, xp_to_add, user_id))
            await db.commit()

            await m.answer(f"✨ <b>МАГИЯ СРАБОТАЛА!</b>\n\n🎁 Твой приз: <b>{prize_text}</b>\n\nНаграда уже в профиле! 🫦", parse_mode="HTML")
            
            builder = InlineKeyboardBuilder()
            builder.button(text="🎙 Записать ГС в ответ", callback_data=f"reply_voice_{user_id}")
            await bot.send_message(ADMIN_ID, f"💰 <b>СУМКА КУПЛЕНА!</b>\nЮзер: {user_link}\nВыпало: {rarity}\nID: <code>{user_id}</code>", reply_markup=builder.as_markup(), parse_mode="HTML")

        # --- 3. ЛОГИКА VIP ПАКЕТОВ (vip_...) ---
        elif payload.startswith("vip_"):
            from datetime import datetime, timedelta
            days_str = payload.replace("vip_", "")
            days = int(days_str)
            
            if days == 999:
                expire_str = None
                label = "НАВСЕГДА"
            else:
                expire_date = datetime.now() + timedelta(days=days)
                expire_str = expire_date.strftime("%Y-%m-%d %H:%M:%S")
                label = f"на {days} дней"

            await db.execute("UPDATE users SET is_vip=1, vip_until=?, xp=xp+1000 WHERE user_id=?", (expire_str, user_id))
            await db.commit()

            await m.answer(f"👑 <b>СТАТУС ОБНОВЛЕН!</b>\n\nТвой VIP-статус {label} активирован. Теперь все двери открыты! 🫦", parse_mode="HTML")
            await bot.send_message(ADMIN_ID, f"👑 <b>НОВЫЙ VIP!</b>\nЮзер: {user_link}\nПакет: {label}\nID: <code>{user_id}</code>", parse_mode="HTML")

        # --- 4. ЛОГИКА ЗВОНКА (call_...) ---
        elif payload.startswith("call_payment_"):
            guy_name = payload.replace("call_payment_", "")
            await m.answer(f"📞 <b>ЗВОНОК ОПЛАЧЕН!</b>\n\nТы заказала звонок от {guy_name}. Марк уже получил уведомление! ❤️", parse_mode="HTML")
            await bot.send_message(ADMIN_ID, f"🚨 <b>ОПЛАЧЕН ЗВОНОК!</b>\nЮзер: {user_link}\nПарень: {guy_name}\nID: <code>{user_id}</code>", parse_mode="HTML")

@dp.message(DragonStates.naming)
async def rename_dragon_finish(m: Message, state: FSMContext):
    new_name = m.text.strip()
    if len(new_name) > 15:
        return await m.answer("⚠️ Давай покороче (до 15 символов).")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE dragon_pet SET dragon_name = ? WHERE user_id = ?", (new_name, m.from_user.id))
        await db.commit()

    await state.clear()
    await m.answer(f"✨ Теперь нашего дракона зовут **{new_name}**.")
    # Исправленный вызов меню:
    await show_dragon_main_menu(m, m.from_user.id, is_callback=False)


@dp.message(CompatibilityStates.wait_partner_bday)
async def comp_final(m: Message, state: FSMContext):
    if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", m.text):
        return await m.answer("⚠️ Введи дату партнера правильно (например: 20.12.1995)")

    data = await state.get_data()
    u_bday = data.get('u_bday')
    p_name = data.get('p_name')
    p_bday = m.text
    
    u = await get_user(m.from_user.id)
    u_name = u[1] or "Красотка"
    b_name = u[5] or "Марк"

    # Считаем числа
    u_num = calculate_numerology(u_bday)
    p_num = calculate_numerology(p_bday)
    
    await m.answer("🔮 **Звезды приходят в движение...** Я рассчитываю ваш код совместимости. Секунду.")
    
    async with ChatActionSender.typing(bot=bot, chat_id=m.chat.id):
        # Формируем запрос к ИИ
        prompt = (
            f"Ты — мистический нумеролог и парень по имени {b_name}. "
            f"Сделай разбор совместимости для пары: {u_name} (Число судьбы: {u_num}) и {p_name} (Число судьбы: {p_num}). "
            f"Используй знания нумерологии. Опиши их сильные стороны, возможные конфликты и дай совет. "
            f"Тон: загадочный, немного романтичный, но честный. В конце напиши процент совместимости (от 70 до 99%)."
        )
        
        result = await get_ai_response(prompt, m.text) # или m.text
        
    kb = await main_kb(m.from_user.id)
    if result:
        await m.answer(f"🌌 **ВАШ ЗВЕЗДНЫЙ ПРОГНОЗ:**\n\n{result}", reply_markup=kb, parse_mode="Markdown")
    else:
        await m.answer("🌌 Звезды сегодня затуманены... Но я и так вижу, что вы — отличная пара! ❤️", reply_markup=kb)
    
    await state.clear()
@dp.callback_query(F.data == "write_admin")
async def write_admin_callback(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.answer(
        "✨ <b>Служба поддержки / Отправка чека</b>\n\n"
        "Пришли скриншот оплаты или опиши свой вопрос ниже.\n"
        "Администратор ответит тебе в ближайшее время:\n\n"
        "<i>Нажми кнопку «Завершить диалог», если захочешь выйти.</i>",
        parse_mode="HTML",
        reply_markup=stop_chat_kb()
    )
    
    # Устанавливаем данные, что мы пишем админу
    await state.update_data(target_guy_id=ADMIN_ID, target_guy_name="Поддержка")
    await state.set_state(ExtraStates.write_admin)
    await c.answer()

# 1. Показ сумки и кнопка оплаты
import random # Убедись, что это в импортах сверху

# --- 1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (ПРИЗЫ И НАЧИСЛЕНИЕ) ---

async def add_xp(user_id: int, amount: int):
    """Начисление XP в базу данных"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET xp = xp + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def get_lootbox_prize():
    """Логика шансов для Тайной Сумки"""
    roll = random.randint(1, 100)
    if roll <= 5:
        return "LEGENDARY", "👑 СТАТУС: НЕВЕСТА МАРКА + 50,000 XP и VIP на месяц!"
    elif roll <= 25:
        return "RARE", "🎙 Личное ГС от Марка + 10,000 XP и VIP на неделю!"
    else:
        return "COMMON", "💰 5,000 XP на твой баланс и VIP на день!"

# --- 2. ПОКАЗ СУМКИ ---

@dp.message(F.text == "🎁 ТАЙНАЯ СУМКА")
async def show_lootbox(m: Message):
    caption = (
        "✨ <b>ТАЙНАЯ СУМКА МАРКА</b> ✨\n\n"
        "Внутри спрятаны редчайшие сокровища Империи. Испытай свою удачу! 🫦\n\n"
        "💎 <b>Что внутри?</b>\n"
        "👑 Статус <b>'НЕВЕСТА МАРКА'</b>\n"
        "🎙 Личное ГС от Марка\n"
        "💰 До 50,000 XP и VIP на месяц!\n\n"
        "💵 <b>Стоимость: 50 ⭐ (Stars)</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 ОТКРЫТЬ ЗА 50 ⭐", callback_data="buy_lootbox_stars")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    from aiogram.types import FSInputFile
    try:
        photo = FSInputFile("bag.png") 
        await m.answer_photo(photo=photo, caption=caption, reply_markup=kb, parse_mode="HTML")
    except:
        await m.answer(caption, reply_markup=kb, parse_mode="HTML")

# --- 3. СОЗДАНИЕ СЧЕТОВ (INVOICES) ---

@dp.callback_query(F.data == "buy_lootbox_stars")
async def create_lootbox_invoice(c: CallbackQuery):
    await c.message.answer_invoice(
        title="Тайная Сумка Марка",
        description="Моментальное открытие сумки с призами!",
        payload="lootbox_stars_payment",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Открытие сумки", amount=50)],
        start_parameter="lootbox"
    )
    await c.answer()

# --- 4. ОБЯЗАТЕЛЬНЫЙ ТЕХНИЧЕСКИЙ ХЕНДЛЕР ---

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

# --- 5. ЕДИНЫЙ ОБРАБОТЧИК УСПЕШНОЙ ОПЛАТЫ ---

# 3. ОБЯЗАТЕЛЬНО: Подтверждение перед оплатой (технический хендлер)

# Хендлер нажатия на кнопку "Записать голосовое"
@dp.callback_query(F.data.startswith("reply_voice_"))
async def start_voice_reply(c: CallbackQuery, state: FSMContext):
    target_id = c.data.replace("reply_voice_", "")
    await state.update_data(reply_to_id=target_id)
    
    await c.message.answer(f"🎙 <b>Жду твое голосовое для пользователя</b> <code>{target_id}</code>\n\nПросто запиши его и отправь мне, а я перешлю.")
    await c.answer()

# Хендлер приема твоего голосового и пересылки девушке
@dp.message(AdminStates.waiting_for_voice, F.voice)
async def process_admin_voice(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("reply_to_id")
    
    try:
        await bot.send_voice(chat_id=target_id, voice=message.voice.file_id)
        await message.answer(f"✅ Твое голосовое сообщение успешно доставлено!")
        await state.clear() # Очищаем состояние
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке: {e}")

# --- ХЕНДЛЕР НАЖАТИЯ НА КНОПКУ ---
# --- ХЕНДЛЕР НАЖАТИЯ НА КНОПКУ ---
@dp.message(F.text == "Твоя тайна в TIKTOK🤫")
async def tiktok_story_start(m: Message, state: FSMContext):
    if not await check_user_or_reg(m, state): return
    
    # Ссылка на твой ТТ (замени на свою актуальную ссылку)
    tiktok_link = "https://www.tiktok.com/@moyparen_bot" 
    
    caption = (
        "🤫 <b>Твоя исповедь останется тайной...</b>\n\n"
        "Расскажи свою самую дикую, грустную или шокирующую историю. "
        "Самые сочные я озвучу и выложу в наш аккаунт:\n"
        f"📱 <a href='{tiktok_link}'><b>НАШ TIKTOK КАНАЛ</b></a>\n\n"
        "⚠️ <b>Это анонимно:</b> твой ник и ID увидит только Марк, "
        "в видео личность будет полностью скрыта.\n\n"
        "👇 <b>Напиши свою историю одним сообщением:</b>"
    )
    
    await m.answer(
        caption,
        parse_mode="HTML",
        disable_web_page_preview=False, # Чтобы появилась превьюшка канала
        reply_markup=stop_chat_kb()
    )
    await state.set_state(ExtraStates.tiktok_story)


# --- ПРИЕМ САМОЙ ИСТОРИИ ---
@dp.message(ExtraStates.tiktok_story)
async def tiktok_story_receive(m: Message, state: FSMContext):
    # Если нажала отмену
    if m.text == "❌ Завершить диалог":
        await state.clear()
        kb = await main_kb(m.from_user.id)
        return await m.answer("Окей, сохраним твои тайны в секрете. Возвращаю в меню.", reply_markup=kb)

    if not m.text:
        return await m.answer("⚠️ Марк ждет именно текстовую историю. Попробуй еще раз!")

    # Отправляем тебе (Админу)
    info_for_admin = (
        f"🔥 <b>НОВЫЙ СЦЕНАРИЙ ДЛЯ TIKTOK!</b>\n\n"
        f"👤 От: {m.from_user.full_name} (ID: <code>{m.from_user.id}</code>)\n"
        f"📝 История:\n\n{m.text}"
    )
    
    await bot.send_message(ADMIN_ID, info_for_admin, parse_mode="HTML")
    
    # Также дублируем в твой лог-канал
    await bot.send_message(LOG_CHANNEL_ID, f"📺 <b>TIKTOK-ЛОГ</b>\n{info_for_admin}", parse_mode="HTML")

    await state.clear()
    kb = await main_kb(m.from_user.id)
    await m.answer("❤️ <b>Твоя история принята...</b>\n\nМарк сохранил её. Следи за нашими соцсетями, возможно именно ты станешь следующей героиней!", reply_markup=kb, parse_mode="HTML")
   
# Хендлер для кнопки "❌ Закрыть"
@dp.callback_query(F.data == "delete_msg")
async def delete_message_handler(c: CallbackQuery):
    try:
        await c.message.delete()
    except Exception as e:
        # Если сообщение уже удалено или это старое сообщение, просто уберем часики на кнопке
        await c.answer("Сообщение уже нельзя удалить", show_alert=False)
    await c.answer()

@dp.callback_query(F.data == "adm_grand_report")
async def grand_report_callback(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: return
    
    await c.answer("📊 Собираю данные... Пожалуйста, подожди.")
    try:
        # Убедись, что здесь НЕТ строки "from __main__ import ..."
        # Просто вызываем функцию:
        await get_and_send_report() 
    except Exception as e:
        logging.error(f"Ошибка гранд-отчета: {e}")
        await c.message.answer(f"❌ Ошибка при генерации гранд-отчета: {e}")

@dp.callback_query(F.data.startswith("adm_del_pic_"))
async def admin_delete_contest_pic(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: return
    
    target_id = int(c.data.split("_")[3])

    async with aiosqlite.connect(DB_PATH) as db:
        # Удаляем из таблицы конкурса
        await db.execute("DELETE FROM weekly_contest WHERE user_id = ?", (target_id,))
        # На всякий случай удаляем и из общей таблицы фото, если она у тебя есть
        await db.execute("DELETE FROM user_photos WHERE user_id = ?", (target_id,))
        await db.commit()

    # Помечаем в канале, что фото удалено
    await c.message.edit_caption(
        caption=c.message.caption + "\n\n✅ <b>УДАЛЕНО ИЗ КОНКУРСА</b>",
        parse_mode="HTML"
    )
    
    # Мягко уведомляем девушку
    try:
        await bot.send_message(target_id, "⚠️ Твой образ не прошел модерацию и был удален из конкурса. Попробуй загрузить другое фото.")
    except: pass

    await c.answer("Удалено из конкурса!", show_alert=True)
# Листание пазла (Callback)

@dp.callback_query(F.data.startswith("puzzle_nav_"))
async def puzzle_navigation(c: CallbackQuery):
    index = int(c.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT puzzle_step FROM users WHERE user_id=?", (c.from_user.id,)) as cursor:
            res = await cursor.fetchone()
    total = res[0] if res else 0
    await send_puzzle_gallery_item(c.message, index, total)
    await c.answer()


def get_survey_kb(selected_features=[]):
    builder = InlineKeyboardBuilder()
    for feat in FEATURES_TO_CHECK:
        # Если фича выбрана, добавляем галочку
        display_text = f"✅ {feat}" if feat in selected_features else feat
        builder.row(InlineKeyboardButton(text=display_text, callback_data=f"survey_toggle:{feat}"))
    
    # Кнопка завершения
    builder.row(InlineKeyboardButton(text="📥 ОТПРАВИТЬ ОТВЕТЫ", callback_data="survey_submit"))
    return builder.as_markup()

def get_dragon_visual(stage, satiety, xp, is_sleeping=0): # Добавили is_sleeping
    try:
        s_idx = int(stage)
    except:
        s_idx = 0

    stages = {
        0: ("🥚 Яйцо", "Оно теплое и мягко светится изнутри."),
        1: ("🦎 Крошка-дракон", "Совсем маленький, учится выпускать искорки."),
        2: ("🐉 Взрослый дракон", "Мощный защитник ваших отношений."),
        3: ("✨ Легендарный Дракон", "Его чешуя сияет как бриллианты.")
    }
    
    if s_idx > 3: s_idx = 3
    name, desc = stages.get(s_idx, stages[0])
    
    # --- ЛОГИКА СНА ---
    if is_sleeping:
        name = f"💤 {name} (спит)"
        desc = "Тссс... Дракон свернулся калачиком и видит десятый сон. Сейчас он почти не тратит силы."
    
    full_blocks = min(5, satiety // 20)
    empty_blocks = 5 - full_blocks
    satiety_bar = "🟢" * full_blocks + "⚪" * empty_blocks
    
    return name, desc, satiety_bar

@dp.message(F.text == "🐲 Наш Дракон")
async def dragon_handler(m: Message):
    # Эта функция теперь просто вызывает универсальный отрисовщик
    await show_dragon_main_menu(m, m.from_user.id)

async def show_dragon_main_menu(message: Message, user_id: int, is_callback=False):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM dragon_pet WHERE user_id = ?", (user_id,)) as cursor:
                dragon = await cursor.fetchone()

        if not dragon:
            return await message.answer("Ошибка: Дракон не найден.")

        d_stage = dragon['stage']
        d_satiety = dragon['satiety']
        d_xp = dragon['dragon_xp']
        d_name = dragon['dragon_name']
        d_is_sleeping = dragon['is_sleeping'] # Достаем статус из БД

        # Передаем статус сна в визуализатор
        stage_name, desc, bar = get_dragon_visual(d_stage, d_satiety, d_xp, d_is_sleeping)

        text = (
            f"🐲 **Ваш питомец: {d_name}**\n"
            f"━━━━━━━━━━━━━━\n"
            f"📊 **Стадия:** {stage_name}\n"
            f"😋 **Сытость:** {bar} ({d_satiety}%)\n"
            f"✨ **Опыт:** {d_xp} XP\n"
            f"━━━━━━━━━━━━━━\n"
            f"📜 **Заметки Марка:**\n_{desc}_\n\n"
            f"Что сделаем для нашего дракона?"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="🥩 Покормить (50 XP)", callback_data="feed_dragon")
        builder.button(text="🧸 Поиграть", callback_data="play_dragon")
        
        # Кнопка СНА меняет текст в зависимости от статуса
        sleep_btn_text = "☀️ Разбудить" if d_is_sleeping else "💤 Уложить спать"
        builder.button(text=sleep_btn_text, callback_data="sleep_dragon")
        
        builder.button(text="📝 Сменить имя", callback_data="rename_dragon")
        builder.adjust(2, 1, 1)

        if is_callback:
            await message.edit_text(text, reply_markup=builder.as_markup())
        else:
            await message.answer(text, reply_markup=builder.as_markup())
            
    except Exception as e:
        logging.error(f"ОШИБКА В show_dragon_main_menu: {e}")

@dp.callback_query(F.data == "feed_dragon")
async def feed_dragon_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Получаем данные (добавляем проверку на None для новичков)
        async with db.execute("SELECT xp FROM users WHERE user_id = ?", (user_id,)) as c:
            user_data = await c.fetchone()
        
        async with db.execute("SELECT satiety, dragon_xp, stage FROM dragon_pet WHERE user_id = ?", (user_id,)) as c:
            dragon_data = await c.fetchone()

        # Если юзер есть, а дракона нет — создаем его принудительно
        if user_data and not dragon_data:
            await db.execute("INSERT INTO dragon_pet (user_id, name, stage, satiety, dragon_xp) VALUES (?, ?, ?, ?, ?)",
                             (user_id, "Малыш", 0, 10, 0))
            await db.commit()
            # Перечитываем данные
            async with db.execute("SELECT satiety, dragon_xp, stage FROM dragon_pet WHERE user_id = ?", (user_id,)) as c:
                dragon_data = await c.fetchone()

        if not user_data:
            return await callback.answer("Ошибка: сначала нажми /start")

        user_xp = user_data[0]
        satiety, d_xp, stage = dragon_data

        # Проверка на стоимость и сытость
        feed_cost = 50
        if user_xp < feed_cost:
            return await callback.answer(f"❌ Мало XP! Нужно {feed_cost}, а у тебя {user_xp}", show_alert=True)
        if satiety >= 100:
            return await callback.answer("🐉 Сыт по горло!", show_alert=True)

        # 2. Расчет эволюции
        new_user_xp = user_xp - feed_cost
        new_satiety = min(100, satiety + 25)
        new_d_xp = d_xp + 15
        new_stage = stage
        
        # ВАЖНО: Проверь, что в БД stage это INTEGER. 
        # Если stage стала 0 (яйцо) — значит где-то в коде ты принудительно ставишь 0.
        if stage == 0 and new_d_xp >= 100:
            new_stage = 1
            await callback.message.answer("🎉 **СОБЫТИЕ!** Яйцо треснуло, появился Крошка-дракон!")

        # 3. Сохраняем
        await db.execute("UPDATE users SET xp = ? WHERE user_id = ?", (new_user_xp, user_id))
        await db.execute(
            "UPDATE dragon_pet SET satiety = ?, dragon_xp = ?, stage = ?, last_fed = ? WHERE user_id = ?", 
            (new_satiety, new_d_xp, new_stage, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id)
        )
        await db.commit()

    await callback.answer(f"🥩 Вкусно! Списано {feed_cost} XP.")
    
    # 4. ОБНОВЛЯЕМ МЕНЮ (Передаем callback, чтобы бот знал user_id)
    # Вместо dragon_handler(callback.message) лучше вызывать функцию, которая принимает ID
    await show_dragon_main_menu(callback.message, user_id, is_callback=True)

@dp.callback_query(F.data == "play_dragon")
async def play_dragon_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Читаем данные (stage, xp, satiety + добавили is_sleeping)
        async with db.execute("SELECT stage, dragon_xp, satiety, is_sleeping FROM dragon_pet WHERE user_id = ?", (user_id,)) as c:
            dragon = await c.fetchone()
        
        if not dragon:
            return await callback.answer("Сначала заведи дракона!", show_alert=True)

        stage, d_xp, satiety, is_sleeping = dragon

        # ПРОВЕРКА 1: Если дракон спит, играть нельзя
        if is_sleeping == 1:
            return await callback.answer("🤫 Тссс, дракон спит! Сначала разбуди его.", show_alert=True)

        # ПРОВЕРКА 2: если сытость 0, играть нельзя
        if satiety <= 0:
            return await callback.answer("🐉 Дракон слишком голоден для игр! Покорми его.", show_alert=True)

        # 2. Логика изменений
        new_xp = d_xp + 10
        # Уменьшаем сытость на 10, но не ниже 0
        new_satiety = max(0, satiety - 10)
        
        new_stage = stage
        if stage == 0 and new_xp >= 100:
            new_stage = 1
            await callback.message.answer("✨ Вау! Твой дракон стал сильнее и перешел на новую стадию!")

        # 3. ЗАПИСЫВАЕМ В БАЗУ
        await db.execute(
            "UPDATE dragon_pet SET dragon_xp = ?, stage = ?, satiety = ? WHERE user_id = ?", 
            (new_xp, new_stage, new_satiety, user_id)
        )
        await db.commit()

    await callback.answer(f"🎮 Поиграли! Опыт: {new_xp}, Сытость: {new_satiety}%")
    
    # 4. ОБНОВЛЯЕМ МЕНЮ (чтобы цифры сразу изменились)
    await show_dragon_main_menu(callback.message, user_id, is_callback=True)

@dp.callback_query(F.data == "sleep_dragon")
async def dragon_sleep_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем текущий статус сна
        async with db.execute("SELECT is_sleeping FROM dragon_pet WHERE user_id = ?", (user_id,)) as c:
            row = await c.fetchone()
            if not row: 
                return await callback.answer("Дракон не найден!")
            
            is_sleeping = row[0]
            # Меняем на противоположный (0 -> 1 или 1 -> 0)
            new_status = 1 if is_sleeping == 0 else 0
            
        # Сохраняем новый статус
        await db.execute("UPDATE dragon_pet SET is_sleeping = ? WHERE user_id = ?", (new_status, user_id))
        await db.commit()

    # Текст для всплывающего уведомления
    status_text = "💤 Дракон уснул. Теперь он медленнее хочет кушать." if new_status == 1 else "☀️ Дракон проснулся и готов к играм!"
    await callback.answer(status_text, show_alert=True)
    
    # ОБНОВЛЯЕМ ИНТЕРФЕЙС
    # Это перерисует меню: изменит описание на "Спит" и текст кнопки на "Разбудить"
    await show_dragon_main_menu(callback.message, user_id, is_callback=True)

@dp.message(Command("clean_chats"))
async def manual_clean_inactive_chats(m: Message):
    if m.from_user.id != ADMIN_ID: return

    # Время 1 час назад
    one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    
    count = 0
    async with aiosqlite.connect(DB_PATH) as db:
        # Ищем модераторов, которые заняты, но не писали больше часа
        async with db.execute(
            "SELECT guy_id, user_id FROM moderator_status WHERE is_busy = 1 AND last_activity < ?", 
            (one_hour_ago,)
        ) as cursor:
            inactive = await cursor.fetchall()
            
        for g_id, u_id in inactive:
            # 1. Сбрасываем базу
            await db.execute("UPDATE moderator_status SET is_busy = 0, user_id = NULL WHERE guy_id = ?", (g_id,))
            
            # 2. Очищаем состояния (FSM), чтобы кнопки меню вернулись
            try:
                u_ctx = dp.fsm.resolve_context(bot, chat_id=u_id, user_id=u_id)
                await u_ctx.clear()
                g_ctx = dp.fsm.resolve_context(bot, chat_id=g_id, user_id=g_id)
                await g_ctx.clear()
                
                # 3. Уведомляем их
                kb_u = await main_kb(u_id)
                await bot.send_message(u_id, "⌛️ **Диалог завершен.**\nВы долго не общались, слот освобожден.", reply_markup=kb_u)
                await bot.send_message(g_id, "⌛️ Чат закрыт по таймеру неактивности.")
                count += 1
            except: pass
            
        await db.commit()

    await m.answer(f"🧹 Уборка завершена! Закрыто «зависших» чатов: **{count}**")

@dp.message(Command("clean_db"))
async def clean_dead_users(m: Message):
    if m.from_user.id != ADMIN_ID: return

    await m.answer("🧹 Начинаю генеральную уборку базы...")
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()

    deleted_count = 0
    for user in users:
        uid = user[0]
        try:
            # Пытаемся проверить статус пользователя
            await bot.send_chat_action(chat_id=uid, action="typing")
        except Exception as e:
            err = str(e).lower()
            if "forbidden" in err or "chat not found" in err or "user_deactivated" in err:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM users WHERE user_id = ?", (uid,))
                    await db.commit()
                deleted_count += 1
        await asyncio.sleep(0.05) # Пауза, чтобы Telegram не ругался

    await m.answer(f"✅ Уборка завершена!\n🗑 Удалено из базы: **{deleted_count}** «мертвых» аккаунтов.", parse_mode="Markdown")

@dp.message(Command("ban"))
async def ban_user_cmd(m: Message):
    if m.from_user.id != ADMIN_ID: return

    args = m.text.split(maxsplit=2)
    if len(args) < 2:
        return await m.answer("⚠️ Формат: `/ban ID ПРИЧИНА`")

    target_id = int(args[1])
    reason = args[2] if len(args) > 2 else "Нарушение правил"

    async with aiosqlite.connect(DB_PATH) as db:
        # Добавляем в бан-лист
        await db.execute("INSERT OR IGNORE INTO banned_users (user_id, reason) VALUES (?, ?)", (target_id, reason))
        # Сразу удаляем из основной таблицы (по желанию)
        await db.execute("DELETE FROM users WHERE user_id = ?", (target_id,))
        await db.commit()

    await m.answer(f"🚫 Пользователь <code>{target_id}</code> заблокирован навсегда.\nПричина: {reason}", parse_mode="HTML")
    
    # Пытаемся отправить прощальное сообщение (если не заблокировала)
    try:
        await bot.send_message(target_id, "❌ Твой доступ к боту ограничен навсегда администрацией.")
    except: pass
@dp.message(RegStates.bot_name)
async def reg_bot_name(m: Message, state: FSMContext):
    await state.update_data(bn=m.text)
    await m.answer("Отличное имя! А какой у меня будет характер? (например: Дерзкий, Романтик, Строгий)")
    await state.set_state(RegStates.bot_style)

@dp.message(RegStates.bot_style)
async def reg_bot_style(m: Message, state: FSMContext):
    await state.update_data(bs=m.text)
    await m.answer("И последнее: какое у меня хобби? Чем я увлекаюсь в свободное время?")
    await state.set_state(RegStates.bot_hobby)

@dp.message(Command("fix_all"))
async def fix_all_users_states(m: Message):
    if m.from_user.id != ADMIN_ID:
        return

    await m.answer("🚀 Начинаю глобальную очистку всех чатов и состояний...")
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()
            
    count = 0
    for user in users:
        uid = user[0]
        try:
            # Сбрасываем FSM для каждого пользователя
            u_ctx = dp.fsm.resolve_context(bot, chat_id=uid, user_id=uid)
            await u_ctx.clear()
            
            count += 1
            if count % 50 == 0:
                await asyncio.sleep(0.2)
        except Exception as e:
            logging.error(f"Ошибка сброса FSM для {uid}: {e}")
            continue

    await m.answer(f"✅ Готово! Очищено состояний для {count} пользователей.")
@dp.message(Command("moders"))
async def check_moders_status(m: Message):
    user_id = m.from_user.id
    
    # ПРОВЕРКА ДОСТУПА: если твой ID равен ADMIN_ID или ты есть в списке модераторов
    # (так как ты сам Марк 25 лет)
    if user_id != ADMIN_ID and user_id not in GUYS_MODERATORS.values():
        return # Если не админ и не модер — молчим

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Получаем всех из таблицы
            async with db.execute(
                "SELECT guy_id, psychotype, is_online FROM moderator_status"
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return await m.answer("📭 Таблица статусов пуста. Попробуй перезапустить бота, чтобы сработал init_db.")

        report = "📊 <b>СТАТУС МОДЕРАТОРОВ:</b>\n\n"
        count_ready = 0
        
        # Создаем список ID, которые реально есть в базе
        db_ids = [row[0] for row in rows]

        for row in rows:
            g_id, p_type, is_online = row
            
            # Ищем имя в твоем словаре GUYS_MODERATORS
            name = "Неизвестный"
            for n, uid in GUYS_MODERATORS.items():
                if uid == g_id:
                    name = n
                    break
            
            status_icon = "✅" if p_type else "❌"
            online_icon = "🟢" if is_online else "⚪"
            type_text = p_type if p_type else "<i>Тест не пройден</i>"
            
            report += f"{status_icon} {online_icon} <b>{name}</b>\n└ Тип: {type_text}\n\n"
            
            if p_type:
                count_ready += 1

        # Проверка: есть ли кто-то в словаре, кого НЕТ в базе
        missing = []
        for name, uid in GUYS_MODERATORS.items():
            if uid not in db_ids:
                missing.append(name)
        
        if missing:
            report += f"⚠️ <b>Нет в базе (ошибка регистрации):</b>\n{', '.join(missing)}\n\n"

        report += f"<b>Всего в словаре: {len(GUYS_MODERATORS)}</b>\n"
        report += f"<b>Прошли тест: {count_ready}</b>"
        
        await m.answer(report, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Ошибка в /moders: {e}")
        await m.answer(f"❌ Ошибка: {e}")
@dp.message(Command("reset_stats"))
async def reset_guy_stats(m: Message):
    if m.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM guy_stats")
        await db.execute("DELETE FROM guy_stats_daily")
        await db.commit()
    
    await m.answer("📈 Статистика (общая и за день) полностью обнулена!")

@dp.message(Command("hot_on", "hot_off"))
async def toggle_hot_status(m: Message):
    if m.from_user.id != ADMIN_ID:
        return 
    
    status = 1 if m.text == "/hot_on" else 0
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE moderator_status SET accepts_hot = ? WHERE guy_id = ?", (status, m.from_user.id))
        await db.commit()
    
    msg = "🫦 **РЕЖИМ ИНТИМА ВКЛЮЧЕН:** Теперь 18+ запросы идут сначала тебе!" if status else "   **РЕЖИМ ИНТИМА ВЫКЛЮЧЕН:** Все 18+ запросы сразу уходят модераторам."
    await m.answer(msg, parse_mode="Markdown")
# --- ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ АДМИНА ---

@dp.message(Command("report"))
async def manual_report(m: Message):
    if m.chat.id == ADMIN_ID:
        # Функция send_detailed_daily_report будет определена позже в блоке CRM
        try:
            await send_detailed_daily_report()
            await m.answer("✅ Отчет сформирован и отправлен!")
        except NameError:
            await m.answer("⚠️ Функция отчета еще не добавлена в код.")

# --- ОБРАБОТКА CALLBACK ЗАПРОСОВ (ЧАСТЬ 1) ---
# Состояние для ожидания нового имени от админа
class AdminState(StatesGroup):
    waiting_for_new_name = State()

@dp.callback_query(F.data.startswith("adm_rename_start_"))
async def start_rename_process(c: CallbackQuery, state: FSMContext):
    target_id = c.data.split("_")[-1]
    await state.update_data(rename_target_id=target_id)
    await state.set_state(AdminState.waiting_for_new_name)
    await c.message.answer(f"📝 Введи новое имя для пользователя <code>{target_id}</code>:", parse_mode="HTML")
    await c.answer()

@dp.message(AdminState.waiting_for_new_name)
async def process_admin_rename(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    
    data = await state.get_data()
    target_id = data.get("rename_target_id")
    new_name = m.text.strip()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET name = ? WHERE user_id = ?", (new_name, target_id))
        await db.commit()

    await m.answer(f"✅ Готово! Теперь её зовут <b>{new_name}</b>", parse_mode="HTML")
    await state.clear()
    
    # Уведомляем её
    try:
        await bot.send_message(target_id, f"✨ Твое новое имя в системе: <b>{new_name}</b>", parse_mode="HTML")
    except: pass

@dp.callback_query(F.data == "adm_toggle_logs")
async def adm_toggle_logs_handler(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: 
        return
    
    # Переключаем в базе (функция асинхронная)
    new_val = await toggle_log_setting()
    
    # Сразу уведомляем
    res_text = "✅ Теперь приходят все сообщения" if new_val == 1 else "📸 Теперь только медиа"
    await c.answer(res_text, show_alert=True)
    
    # Вызываем заново функцию админки, чтобы обновить кнопки
    try:
        # Пытаемся вызвать функцию админ-панели (она будет в блоке CRM)
        from __main__ import adm 
        await adm(c.message)
    except Exception:
        # Если функции еще нет или ошибка — просто удаляем старое, чтобы не плодить сообщения
        await c.message.delete()

# --- ТЕХНИЧЕСКИЕ И БОНУСНЫЕ КОМАНДЫ ---
@dp.message(Command("check_db"))
async def check_db(m: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            res_total = await cursor.fetchone()
            total = res_total[0] if res_total else 0
        
        # Попробуем найти тех, у кого заполнено имя (значит они прошли регистрацию)
        async with db.execute("SELECT COUNT(*) FROM users WHERE u_name IS NOT NULL") as cursor:
            res_name = await cursor.fetchone()
            with_name = res_name[0] if res_name else 0
            
    await m.answer(f"📊 Всего в базе: {total}\n✅ Прошли регистрацию: {with_name}")
# --- УПРАВЛЕНИЕ БАЛАНСОМ И СТАТУСАМИ ---


@dp.message(Command("online", "offline"))
async def toggle_status(m: Message):
    # Проверка, что пишет кто-то из списка модераторов
    if m.from_user.id not in GUYS_MODERATORS.values(): 
        return
    
    if m.text == "/online":
        status_int = 1
        busy_int = 0  # Освобождаем при входе
        msg = "✅ Ты в сети и СВОБОДЕН! Девушки видят тебя. 🟢"
    else:
        status_int = 0
        busy_int = 0
        msg = "💤 Ты ушел в офлайн."
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE moderator_status SET is_online = ?, is_busy = ? WHERE guy_id = ?", 
            (status_int, busy_int, m.from_user.id)
        )
        await db.commit()
    await m.answer(msg)

# --- АВТО-ОТМЕНА СОСТОЯНИЙ ПРИ ПЕРЕХОДЕ В МЕНЮ ---

@dp.message(GiftStates.waiting_for_receiver, F.text.in_(MENU_BUTTONS))
async def auto_cancel_gift_on_menu(m: Message, state: FSMContext):
    await state.clear()
    # Предполагается, что функция ai будет определена ниже для обработки логики ИИ и меню
    try:
        from __main__ import ai
        return await ai(m, state)
    except ImportError:
        # Если ai еще не определена, просто отправим главное меню
        kb = await main_kb(m.from_user.id)
        await m.answer("Действие отменено.", reply_markup=kb)
# --- ОТЧЕТЫ И МАГАЗИН (ЧАСТЬ 1) ---

@dp.callback_query(F.data == "adm_guy_stats")
async def show_guy_stats_callback(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: 
        return

    today_db = datetime.now().strftime("%Y-%m-%d")
    
    # Данные за сегодня
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT guy_name, chats_count FROM guy_stats_daily WHERE date = ? ORDER BY chats_count DESC", 
            (today_db,)
        ) as cursor:
            stats_today = await cursor.fetchall()

    msg = f"📈 **ОТЧЕТ ПО ПАРНЯМ ({today_db})**\n"
    msg += "━━━━━━━━━━━━━━\n\n"
    
    if not stats_today:
        msg += "Сегодня активности пока не было. 💤\n"
    else:
        for i, (name, count) in enumerate(stats_today, 1):
            msg += f"{i}. {name}: **{count}** диалогов за сегодня\n"

    msg += "\n🔍 **КТО СЕЙЧАС В ЧАТАХ:**\n"
    active_found = False
    for name, uid in GUYS_MODERATORS.items():
        # Проверяем FSM состояние каждого парня
        state_obj = dp.fsm.resolve_context(bot, chat_id=uid, user_id=uid)
        curr_state = await state_obj.get_state()
        if curr_state == ExtraStates.live_chat.state: # .state для корректного сравнения
            msg += f"🔥 **{name}** на линии\n"
            active_found = True
            
    if not active_found:
        msg += "Никто не ведет диалог в данный момент."

    await c.message.answer(msg, parse_mode="Markdown")
    await c.answer()

@dp.callback_query(F.data == "rename_dragon")
async def rename_dragon_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "📝 **Как мы назовем нашего защитника?**\n\n"
        "Напиши имя для дракона одним словом (например, *Арчи, Сириус или Огонек*):"
    )
    await state.set_state(DragonStates.naming)
@dp.message(DragonStates.naming)
async def rename_dragon_finish(m: Message, state: FSMContext):
    new_name = m.text.strip()
    
    # Небольшая проверка на длину
    if len(new_name) > 15:
        return await m.answer("⚠️ Ого, какое длинное имя! Давай покороче (до 15 символов).")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE dragon_pet SET dragon_name = ? WHERE user_id = ?", 
            (new_name, m.from_user.id)
        )
        await db.commit()

    await state.clear()
    await m.answer(f"✨ Прекрасный выбор! Теперь нашего дракона зовут **{new_name}**.")
    
    # Сразу показываем обновленную карточку
    # Для этого нам нужно получить данные дракона заново
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT stage, satiety, dragon_xp, dragon_name FROM dragon_pet WHERE user_id = ?", (m.from_user.id,)) as cursor:
            dragon = await cursor.fetchone()
    
    if dragon:
        await m.answer("Вот как он выглядит теперь:")
        # Здесь мы просто вызываем наш ранее написанный dragon_handler
        # Но так как dragon_handler ожидает Message, мы можем просто сэмулировать вызов:
        await show_dragon_main_menu(callback.message, user_id, is_callback=True)

@dp.callback_query(F.data == "buy_vip_24")
async def desc_vip_day(c: CallbackQuery):
    text = (
        "👑 **VIP-СТАТУС НА СУТКИ**\n\n"
        "Хочешь попробовать все привилегии прямо сейчас? "
        "Активируй VIP на 24 часа за игровые баллы!\n\n"
        "🔹 Безлимитное общение с реальными парнями.\n"
        "🔹 Безлимитная оценка твоих образов.\n"
        "🔹 Доступ к разделу 18+ Сокровенное.\n"
        "🔹 Приоритет в очереди на поиск подружки.\n\n"
        "💰 Стоимость: **1500 XP**"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Активировать на день", callback_data="confirm_buy_vip_24")],
        [InlineKeyboardButton(text="⬅️ Назад в магазин", callback_data="back_to_shop")]
    ])
    await c.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
# --- МАГАЗИН И АДМИН-ВЫДАЧА VIP ---


@dp.callback_query(F.data.startswith("give_vip_"))
async def admin_give_vip_select(call: CallbackQuery):
    # Вытаскиваем ID пользователя из callback_data
    target_id = call.data.replace("give_vip_", "")
    
    # Создаем кнопки выбора срока
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎫 7 дней", callback_data=f"set_vip_{target_id}_7"),
            InlineKeyboardButton(text="🔥 30 дней", callback_data=f"set_vip_{target_id}_30")
        ],
        [InlineKeyboardButton(text="♾ Навсегда", callback_data=f"set_vip_{target_id}_9999")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_admin")]
    ])
    
    await call.message.edit_text(
        f"На какой срок выдаем VIP пользователю <code>{target_id}</code>?", 
        parse_mode="HTML", 
        reply_markup=kb
    )

# --- АДМИН-ФУНКЦИИ: ВЫДАЧА VIP И ПОПЫТОК ---

@dp.callback_query(F.data.startswith("set_vip_"))
async def admin_set_vip_final(call: CallbackQuery):
    # Разбираем данные (формат: set_vip_ID_DAYS)
    data = call.data.split("_")
    target_id = data[2]
    days = int(data[3])
    
    # Расчет даты окончания
    if days == 9999:
        expire_date = datetime.now() + timedelta(days=36500) # Навсегда (~100 лет)
        label = "навсегда"
    else:
        expire_date = datetime.now() + timedelta(days=days)
        label = f"на {days} дн."
    
    expire_str = expire_date.strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. Записываем в базу данных
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET is_vip = 1, vip_until = ? WHERE user_id = ?", 
            (expire_str, target_id)
        )
        await db.commit()
    
    # 2. Формируем текст для админа
    res_text = (
        f"✅ <b>VIP ВЫДАН {label.upper()}!</b>\n"
        f"👤 ID: <code>{target_id}</code>\n"
        f"📅 Срок до: <code>{expire_str.split(' ')[0]}</code>"
    )
    
    # 3. Кнопка «Ответить», чтобы сразу вернуться к диалогу
    kb_back = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить девушке", callback_data=f"chat_{target_id}")]
    ])
    
    # ПРОВЕРКА: Если выдаем VIP на сообщении с ФОТО (чеком), используем edit_caption
    try:
        if call.message.photo:
            await call.message.edit_caption(caption=res_text, reply_markup=kb_back, parse_mode="HTML")
        else:
            await call.message.edit_text(text=res_text, reply_markup=kb_back, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка обновления сообщения админа: {e}")

    # 4. Уведомляем пользователя
    try:
        if days == 1:
            msg_text = (
                "🎁 <b>ТЕБЕ ПОДАРОК!</b>\n\n"
                "Администратор открыл тебе <b>VIP-доступ на 24 часа</b>! 👑\n"
                "Теперь ты можешь зайти в раздел <b>18+ Сокровенное</b> и общаться без ограничений. Попробуй прямо сейчас! ❤️"
            )
        else:
            msg_text = (
                "👑 <b>ОПЛАТА ПОДТВЕРЖДЕНА!</b>\n\n"
                f"Тебе активирован <b>VIP-статус {label}</b>. "
                "Теперь все ограничения сняты, наслаждайся общением! ❤️"
            )
        await bot.send_message(target_id, msg_text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Не удалось отправить уведомление пользователю: {e}")
    
    await call.answer(f"Выдано {label}")
@dp.message(Command("reset_me"))
async def hard_reset_user(m: Message, state: FSMContext):
    user_id = m.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Убрали 'diary' и 'time_capsules' из списка
        tables = [
            "users", "dragon_pet", "user_stats_daily"
        ]
        
        for table in tables:
            try:
                # В большинстве твоих таблиц колонка называется user_id
                await db.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            except Exception as e:
                logging.error(f"Ошибка при очистке таблицы {table}: {e}")
        
        await db.commit()

    await state.clear()
    await m.answer(
        "♻️ **ПЕРЕЗАГРУЗКА ПРОФИЛЯ**\n\n"
        "Твой ранг, XP и настройки персонажа сброшены. Твой Дракон тоже покинул тебя...\n\n"
        "🔒 **Но не волнуйся:** Твой секретный дневник и капсулы времени остались нетронутыми. Они ждут тебя!\n\n"
        "Пиши /start, чтобы начать всё заново. ❤️"
    )


@dp.callback_query(F.data == "go_to_vip_section")
async def vip_shop_stars(c: CallbackQuery):
    # Удаляем старое сообщение или просто редактируем
    text = (
        "👑 **МАГАЗИН VIP-СТАТУСОВ (STARS)**\n\n"
        "Выбери подходящий пакет. Оплата звездами мгновенная и безопасная!\n\n"
        "🔸 **VIP на 24 часа** — Попробовать все функции\n"
        "🔸 **VIP на 7 дней** — Неделя без ограничений\n"
        "🔸 **VIP на 30 дней** — Полное погружение\n"
        "🔸 **VIP НАВСЕГДА** — Стань легендой Империи"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Сутки — 50 ⭐", callback_data="buy_xtr_1")],
        [InlineKeyboardButton(text="💎 Неделя — 150 ⭐", callback_data="buy_xtr_7")],
        [InlineKeyboardButton(text="🔥 Месяц — 450 ⭐", callback_data="buy_xtr_30")],
        [InlineKeyboardButton(text="♾ Навсегда — 1500 ⭐", callback_data="buy_xtr_999")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    await c.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await c.answer()

# Обработчик нажатия на кнопку покупки
@dp.callback_query(F.data.startswith("buy_xtr_"))
async def send_star_invoice(c: CallbackQuery):
    days = c.data.split("_")[2]
    
    # Сопоставляем дни и цены
    prices = {
        "1": 50,
        "7": 150,
        "30": 450,
        "999": 1500
    }
    
    amount = prices.get(days, 50)
    
    await c.message.answer_invoice(
        title=f"VIP Статус ({days if days != '999' else 'Навсегда'})",
        description=f"Активация всех функций Марка на выбранный срок.",
        payload=f"vip_{days}", # Важно! Этот текст придет в успешной оплате
        provider_token="",     # Для Stars пусто
        currency="XTR",
        prices=[LabeledPrice(label="VIP Access", amount=amount)],
        start_parameter="vip-stars"
    )
    await c.answer()

@dp.callback_query(F.data == "cancel_hot_chat")
async def cancel_hot(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text("🔒 Ты вышла из секретного раздела. Возвращаю тебя в меню.")
    await c.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_handler(c: CallbackQuery):
    await c.message.edit_text("Вы вернулись в главное меню. Используйте кнопки внизу. 👇")
    await c.answer()

@dp.callback_query(F.data == "buy_more_profile")
async def buy_from_profile(c: CallbackQuery):
    text = (
        "<b>💳 ПОПОЛНЕНИЕ БАЛАНСА</b>\n\n"
        "💎 VIP-статус (безлимит): 500р\n"
        "🎫 Доп. попытки (5 шт): 100р\n\n"
        f"Реквизиты: <code>{CARD_DETAILS}</code>\n\n"
        "После оплаты пришли чек в поддержку (кнопка ✍️ Написать админу)"
    )
    await c.message.answer(text, parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data.startswith("give_chat_"))
async def give_chat_btn(c: CallbackQuery):
    uid = int(c.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET tries_chat = tries_chat + 5 WHERE user_id = ?", (uid,))
        await db.commit()
    await c.answer("✅ +5 попыток чата выдано!", show_alert=True)
    try:
        await bot.send_message(uid, "🎫 Тебе начислено +5 попыток общения с реальным парнем! 🔥")
    except: pass
@dp.message(F.text == "/adm_clear_gossip")
async def manual_adm_clear(m: Message):
    # Проверка, что это ТЫ (админ)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM gossip_history")
        await db.commit()
    await m.answer("🧹 Я всё вычистил, хозяйка. История сплетен пуста.")

@dp.callback_query(F.data == "adm_clear_gossip")
async def clear_gossip(c: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            # Используем точное имя из твоей базы
            await db.execute("DELETE FROM gossip_history")
            await db.commit()
            await c.answer("🧹 История сплетен полностью очищена!", show_alert=True)
        except Exception as e:
            logging.error(f"Ошибка при очистке gossip_history: {e}")
            await c.answer("❌ Ошибка при удалении данных", show_alert=True)

@dp.callback_query(F.data == "adm_manage_user")
async def manage_user_start(c: CallbackQuery, state: FSMContext):
    await c.message.answer("🆔 Введи Telegram ID пользователя:")
    await state.set_state(AdminStates.manage_user_id)
    await c.answer()

@dp.message(AdminStates.manage_user_id)
async def user_info(m: Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("Введи только цифры (ID).")
    
    uid = int(m.text)
    u = await get_user(uid) # get_user асинхронная
    if not u:
        return await m.answer("❌ Пользователь не найден в базе.")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Выдать VIP", callback_data=f"give_vip_{uid}")],
        [InlineKeyboardButton(text="➕ Дать +5 чатов", callback_data=f"give_chat_{uid}")],
        [InlineKeyboardButton(text="❌ Удалить юзера", callback_data=f"del_user_{uid}")]
    ])
    
    # Индексы согласно твоей таблице users: 1-u_name, 8-xp, 9-tries_chat
    text = (
        f"👤 **Управление пользователем:**\n"
        f"Имя: {u[1] if u[1] else 'Не указано'}\n"
        f"ID: `{uid}`\n"
        f"XP: {u[8]}\n"
        f"Попыток чата: {u[9]}"
    )
    await m.answer(text, reply_markup=kb, parse_mode="Markdown")
    await state.clear()
# --- ГОЛОСОВЫЕ И ПОДАРКИ (ЛОГИКА ПЕРЕВОДА) ---

# --- @dp.message(F.voice)
# --- async def get_voice_id(m: Message):
# ---    await m.answer(f"ID твоего голосового:\n`{m.voice.file_id}`", parse_mode="Markdown")

# Шаг 1: Ловим ID получателя

@dp.callback_query(F.data.startswith("selectguy_"))
async def select_guy_callback(c: CallbackQuery, state: FSMContext):
    # Разбираем данные из кнопки
    guy_name = c.data.split("_")[1]
    guy_id = GUYS_MODERATORS.get(guy_name)
    user_id = c.from_user.id 

    # 1. ПРОВЕРКА VIP ДЛЯ МАРКА
    if "Марк" in guy_name:
        u = await get_user(user_id)
        # Индекс 2 в твоей базе — это статус VIP (1 или 0)
        is_vip = u[2] if u else 0
        
        if not is_vip:
            kb_vip = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 КУПИТЬ VIP", callback_data="go_to_vip_section")],
                [InlineKeyboardButton(text="⬅️ Назад к парням", callback_data="back_to_guys")]
            ])
            return await c.message.edit_text(
                "👑 <b>МАРК — ЭТО ЭКСКЛЮЗИВНЫЙ ВЫБОР</b>\n\n"
                "Малыш, этот парень общается только с обладательницами <b>VIP-статуса</b>. "
                "Он ценит свое время и выбирает только самых преданных королев.\n\n"
                "Хочешь открыть доступ к общению с ним?",
                reply_markup=kb_vip, 
                parse_mode="HTML"
            )

    # 2. ПРОВЕРКА СТАТУСА ПАРНЯ В БД
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT is_online, is_busy FROM moderator_status WHERE guy_id=?", 
            (guy_id,)
        ) as cursor:
            mod_row = await cursor.fetchone()
    
    # Если парень оффлайн
    if not mod_row or not mod_row[0]:
        return await c.answer(f"❌ {guy_name} сейчас оффлайн. Выбери того, кто в сети (🟢)!", show_alert=True)

    # Если парень занят
    if mod_row[1] == 1:
        return await c.answer(
            f"⏳ {guy_name} сейчас на свидании с другой девушкой...\n\n"
            f"Подожди пару минут или выбери другого свободного парня! 😉", 
            show_alert=True
        )

    # 3. ЛОГИКА НОЧНОГО ВРЕМЕНИ
    # Используем стабильный вызов времени (учитывая твои импорты)
    try:
        current_hour = datetime.now().hour
    except:
        import datetime as dt_module
        current_hour = dt_module.datetime.now().hour
    
    # Считаем ночь с 00:00 до 08:00 утра
    if 0 <= current_hour < 8:
        welcome_text = (
            f"Ты выбрала {guy_name}. Он будет очень рад пообщаться! У него есть 10 минут чтоб ответить тебе ✨\n\n"
            "Но помни: наши модераторы-парни могут быть заняты в даный момент и ночью тоже спят. "
            "Так что ответят только утром. Пиши всё, что хочешь, "
            "он прочитает это первым делом! ☕️ Если он надоест нажми завершить диалог"
        )
    else:
        welcome_text = (
            f"Ты выбрала {guy_name}. Он будет очень рад пообщаться!У него есть 10 минут чтоб ответить тебе ✨\n\n"
            "Но помни: наши модераторы-парни ночью тоже спят. "
            "Так что ответят только утром. Пиши всё, что хочешь, "
            "он прочитает это первым делом! ☕️Если он надоест нажми завершить диалог"
        )
    # 4. ОБНОВЛЯЕМ СТАТУС В БАЗЕ (Занимаем парня)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE moderator_status SET is_busy = 1 WHERE guy_id=?", (guy_id,))
        await db.commit()

    # 5. Девушке ставим чат
    await state.update_data(target=guy_id, target_name=guy_name, was_answered=False)
    await state.set_state(ExtraStates.live_chat)

    # --- 6. ПАРНЮ ШЛЕМ ПОДРОБНУЮ ИНФОРМАЦИЮ ---
    
    # 1. Получаем имя из твоей базы данных
    u_girl = await get_user(user_id)
    db_name = u_girl[1] if u_girl and u_girl[1] else "Не указано"
    
    # 2. Получаем данные напрямую из Telegram профиля
    tg_first_name = c.from_user.first_name or ""
    tg_last_name = c.from_user.last_name or ""
    tg_full_name = f"{tg_first_name} {tg_last_name}".strip()
    tg_username = f"@{c.from_user.username}" if c.from_user.username else "скрыт"

    # 3. Формируем кнопку
    kb_accept = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🫦 ОТВЕТИТЬ КРАСОТКЕ", callback_data=f"chat_{user_id}")]
    ])

    # 4. Текст уведомления (с именами и ID)
    # Вместо старого notification_text:
    detail_text = await get_detailed_user_info(user_id, c.from_user, "🔔 НОВЫЙ ЗАПРОС (РЕАЛЬНЫЙ ПАРЕНЬ)")
    
    try:
        await bot.send_message(guy_id, detail_text, parse_mode="HTML", reply_markup=kb_accept)
    except Exception as e:
        logging.error(f"Ошибка: {e}")


    try:
        await bot.send_message(
            guy_id, 
            notification_text,
            parse_mode="HTML",
            reply_markup=kb_accept
        )
    except Exception as e:
        logging.error(f"Ошибка уведомления модератора {guy_id}: {e}")

    # 7. Таймер на 10 минут
    # Исправлен порядок аргументов: сначала девушка (user_id), потом парень (guy_id)
    # Используем 'date' вместо 'interval', чтобы задача сработала строго один раз
    # 7. Таймер на 10 минут (ИСПРАВЛЕННЫЙ)
    # Используем тот же пояс, что и во всем боте
    kz_tz = pytz.timezone("Asia/Almaty")
    run_time = datetime.now(kz_tz) + timedelta(minutes=10)

    scheduler.add_job(
        check_guy_response,
        "date",
        run_date=run_time, 
        args=[user_id, guy_id],
        id=f"wait_reply_{user_id}",
        replace_existing=True
    )
    # 8. ОТВЕТ ПОЛЬЗОВАТЕЛЮ
    await c.message.answer(
        welcome_text, 
        reply_markup=stop_chat_kb()
    )
    
    await c.answer()

# --- УМНАЯ РАССЫЛКА С ОЧИСТКОЙ БАЗЫ ---

@dp.callback_query(F.data == "adm_broadcast")
async def start_broadcast(c: CallbackQuery, state: FSMContext):
    await c.message.answer("📝 Введи текст сообщения для рассылки (или нажми /cancel):")
    await state.set_state(AdminStates.broadcast_msg)
    await c.answer()

@dp.message(AdminStates.broadcast_msg)
async def perform_broadcast(m: Message, state: FSMContext):
    if m.text == "/cancel": 
        await state.clear()
        return await m.answer("Отменено.")
    
    # Исключаем админа и модераторов из рассылки
    exclude_ids = list(GUYS_MODERATORS.values())
    if ADMIN_ID not in exclude_ids:
        exclude_ids.append(ADMIN_ID)

    # Получаем список пользователей
    placeholders = ', '.join(['?'] * len(exclude_ids))
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT user_id, last_seen FROM users WHERE user_id NOT IN ({placeholders})", 
            exclude_ids
        ) as cursor:
            users = await cursor.fetchall()
    
    total_in_db = len(users)
    count_success = 0
    count_blocked_and_deleted = 0
    count_saved_by_date = 0 
    
    await m.answer(f"🚀 Рассылка на {total_in_db} чел. с проверкой даты посещения...")
    
    for user in users:
        uid = user[0]
        last_act_str = user[1] 
        
        try:
            await bot.send_message(uid, m.text)
            count_success += 1
            await asyncio.sleep(0.05) # Защита от спам-фильтра
        except Exception as e:
            err_msg = str(e).lower()
            
            # Если бот заблокирован или юзер удален
            if any(text in err_msg for text in ["forbidden", "chat not found", "user_deactivated"]):
                is_old = True
                if last_act_str:
                    try:
                        # Считаем разницу во времени
                        last_act_dt = datetime.strptime(last_act_str, '%Y-%m-%d %H:%M:%S')
                        if datetime.now() - last_act_dt < timedelta(days=3):
                            is_old = False # Юзер свежий, не трогаем
                    except Exception:
                        pass

                if is_old:
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute("DELETE FROM users WHERE user_id = ?", (uid,))
                        await db.commit()
                    count_blocked_and_deleted += 1
                else:
                    count_saved_by_date += 1
            continue
        
    await m.answer(
        f"✅ **ИТОГ РАССЫЛКИ:**\n"
        f"━━━━━━━━━━━━━━\n"
        f"📨 Доставлено: **{count_success}**\n"
        f"🧹 Удалено (давно не заходили + блок): **{count_blocked_and_deleted}**\n"
        f"🛡 Помиловано (свежие, но с ошибкой): **{count_saved_by_date}**\n"
        f"📊 Осталось в базе: **{total_in_db - count_blocked_and_deleted}**"
    )
    await state.clear()
# --- ПРИВАТНЫЕ ОБРАЗЫ И ЗАКАЗ ЗВОНКОВ ---

@dp.callback_query(F.data == "contest_no")
async def contest_decline(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("temp_photo_id")
    user_cap = data.get("temp_caption", "")
    user_id = c.from_user.id
    
    if not file_id:
        return await c.answer("❌ Фото потеряно, пришли еще раз.", show_alert=True)

    # 1. Получаем имя из твоей базы данных
    u_girl = await get_user(user_id)
    db_name = u_girl[1] if u_girl and u_girl[1] else "Не указано"
    
    # 2. Получаем данные напрямую из Telegram
    tg_full_name = c.from_user.full_name
    tg_username = f"@{c.from_user.username}" if c.from_user.username else "скрыт"

    # Кнопка для админа, чтобы сразу перейти в чат
    kb_admin = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить / Оценить", callback_data=f"chat_{user_id}")],
        [InlineKeyboardButton(text="✏️ Изменить имя", callback_data=f"adm_rename_start_{user_id}")]
    ])
    
    # Формируем подробный текст
    admin_info = (
        f"👗 <b>ПРИВАТНАЯ ОЦЕНКА ОБРАЗА</b>\n\n"
        f"👤 <b>В боте:</b> {db_name}\n"
        f"📱 <b>В Telegram:</b> {tg_full_name}\n"
        f"🔗 <b>Username:</b> {tg_username}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n\n"
        f"📝 <b>Текст от неё:</b> {user_cap if user_cap else '<i>без описания</i>'}"
    )

    try:
        # Отправляем фото админу
        await bot.send_photo(
            chat_id=ADMIN_ID, 
            photo=file_id, 
            caption=admin_info, 
            reply_markup=kb_admin,
            parse_mode="HTML"
        )
        # Уведомляем девушку (редактируем сообщение с кнопками)
        await c.message.edit_text("Принято! Твой образ увижу только я. Скоро пришлю свою оценку... 🫦")
        
    except Exception as e:
        logging.error(f"ОШИБКА отправки приватного фото: {e}")
        await c.answer("⚠️ Ошибка отправки админу.", show_alert=True)

    await state.clear()
    await c.answer()

@dp.callback_query(F.data == "buy_call")
async def process_call_quick_order(c: CallbackQuery):
    # 1. Текст с условиями для девушки
    text = (
        "📞 <b>ЛИЧНЫЙ ЗВОНОК ОТ ПАРНЯ</b>\n\n"
        "Эта услуга позволяет тебе созвониться с любым из наших парней и пообщаться в реальности. "
        "Он выслушает, поддержит или просто составит тебе компанию. 🫦\n\n"
        "💰 <b>Стоимость: 500₽</b>\n"
        "🎁 <b>Бонус:</b> При оплате звонка ты получаешь VIP-статус на 24 часа бесплатно!\n\n"
        "<i>Нажми кнопку ниже для оплаты, а после пришли чек администратору.</i>"
    )

    # 2. Кнопки: Оплата, Чек и Назад
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 ОПЛАТИТЬ 500₽", url=DONATION_URL)],
        [InlineKeyboardButton(text="✅ Я оплатила (отправить чек)", callback_data="write_admin")],
        [InlineKeyboardButton(text="⬅️ Назад к списку парней", callback_data="back_to_guys")]
    ])
    
    # 3. Редактируем старое сообщение, чтобы всё выглядело аккуратно
    try:
        await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        # Если вдруг edit не сработал (например, сообщение старое), шлем новое
        await c.message.answer(text, reply_markup=kb, parse_mode="HTML")
        
    await c.answer()
# --- КНОПКИ МЕНЮ: СТАТИСТИКА ПАРНЕЙ ---
@dp.message(F.text == "💌 Капсула времени")
async def capsule_start(m: Message, state: FSMContext):
    if not await check_user_or_reg(m, state): return
    await m.answer(
        "✨ **ДОБРО ПОЖАЛОВАТЬ В БУДУЩЕЕ...**\n\n"
        "Я могу спрятать твое послание (текст, фото или голос) и вернуть его тебе "
        "ровно через то время, которое ты выберешь. Это будет твой привет из прошлого.\n\n"
        "📸 **Пришли мне то, что хочешь запечатать:**",
        reply_markup=stop_chat_kb()
    )
    await state.set_state(CapsuleStates.waiting_for_content)

@dp.message(CapsuleStates.waiting_for_content)
async def capsule_content(m: Message, state: FSMContext):
    # 1. ПЕРВЫМ ДЕЛОМ: проверяем, не нажал ли юзер кнопку выхода
    if m.text == "❌ Завершить диалог" or m.text == "🚪 Выйти":
        await state.clear()
        kb = await main_kb(m.from_user.id)
        return await m.answer("🔒 Создание капсулы отменено. Возвращаю тебя в меню.", reply_markup=kb)

    content = None
    media_type = None

    # Логирование в канал (оставляем твой код)
    try:
        user_info = (
            f"📥 **Новая капсула времени!**\n"
            f"👤 От: {m.from_user.full_name}\n"
            f"🆔 ID: <code>{m.from_user.id}</code>"
        )
        await bot.send_message(LOG_CHANNEL_ID, user_info, parse_mode="HTML")
        await m.copy_to(LOG_CHANNEL_ID)
    except Exception as e:
        logging.error(f"Ошибка логирования капсулы: {e}")

    # 2. Обработка контента
    if m.text:
        content = m.text
        media_type = "text"
    elif m.photo:
        content = m.photo[-1].file_id
        media_type = "photo"
    elif m.voice:
        content = m.voice.file_id
        media_type = "voice"
    else:
        return await m.answer("⚠️ Я принимаю только текст, фото или голосовые сообщения.")

    await state.update_data(c_content=content, c_type=media_type)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ 1 Месяц", callback_data="capsule_1m")],
        [InlineKeyboardButton(text="⏳ 6 Месяцев", callback_data="capsule_6m")],
        [InlineKeyboardButton(text="🗓 1 Год", callback_data="capsule_1y")],
        [InlineKeyboardButton(text="📅 Своя дата", callback_data="capsule_custom")]
    ])
    
    await m.answer("🔒 Послание принято! Теперь выбери срок хранения:", reply_markup=kb)
    await state.set_state(CapsuleStates.waiting_for_date)
@dp.callback_query(CapsuleStates.waiting_for_date, F.data.startswith("capsule_"))
async def capsule_date_select(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    now = datetime.now()
    send_at = None

    if c.data == "capsule_1m":
        send_at = (now + timedelta(days=30)).strftime("%Y-%m-%d")
    elif c.data == "capsule_6m":
        send_at = (now + timedelta(days=182)).strftime("%Y-%m-%d")
    elif c.data == "capsule_1y":
        send_at = (now + timedelta(days=365)).strftime("%Y-%m-%d")
    elif c.data == "capsule_custom":
        await c.message.answer("Введи дату в формате ДД.ММ.ГГГГ (например: 15.05.2026):")
        return await c.answer()

    if send_at:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO time_capsules (user_id, content, media_type, send_at) VALUES (?, ?, ?, ?)",
                (c.from_user.id, data['c_content'], data['c_type'], send_at)
            )
            await db.commit()
        
        await c.message.answer(f"✅ **КАПСУЛА ЗАПЕЧАТАНА!**\n\nЯ верну тебе это воспоминание **{send_at}**. Не забудь заглянуть ко мне в этот день! 😉", reply_markup=await main_kb(c.from_user.id))
        await state.clear()
    await c.answer()

@dp.message(CapsuleStates.waiting_for_date)
async def capsule_custom_date(m: Message, state: FSMContext):
    if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", m.text):
        return await m.answer("⚠️ Введи дату правильно: ДД.ММ.ГГГГ")
    
    try:
        date_obj = datetime.strptime(m.text, "%d.%m.%Y")
        if date_obj <= datetime.now():
            return await m.answer("⚠️ Дата должна быть в будущем!")
        
        send_at = date_obj.strftime("%Y-%m-%d")
        data = await state.get_data()
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO time_capsules (user_id, content, media_type, send_at) VALUES (?, ?, ?, ?)",
                (m.from_user.id, data['c_content'], data['c_type'], send_at)
            )
            await db.commit()

        await m.answer(f"✅ **ГОТОВО!**\nПослание спрятано до **{send_at}**.", reply_markup=await main_kb(m.from_user.id))
        await state.clear()
    except:
        await m.answer("❌ Ошибка в дате. Попробуй еще раз.")

# 1. Меню выбора
@dp.message(F.text == "🔥 Горячий Марк")
async def hot_mark_menu(m: Message):
    # Текст для привлечения внимания
    text = (
        "Малыш, ты зашла в мой секретный архив... ✨\n\n"
        "Здесь собраны кадры, которые я не показываю обычным знакомым. "
        "Выбирай, что ты хочешь увидеть сегодня? 🫦\n\n"
        "<i>Оплата моментальная через Telegram Stars ⭐</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧩 Кусочек пазла — 15 ⭐", callback_data="buy_hot_part")],
        [InlineKeyboardButton(text="👖 80% Тела — 150 ⭐", callback_data="buy_hot_bottom")],
        [InlineKeyboardButton(text="📸 ПОЛНЫЙ ФУЛЛ — 250 ⭐", callback_data="buy_hot_full")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    
    # Можно добавить "заблюренное" превью фото, если есть bag.png или подобное
    await m.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_hot_"))
async def create_hot_invoice(c: CallbackQuery):
    action = c.data.replace("buy_hot_", "")
    
    prices = {
        "part": ("Кусочек пазла Марка", 15),
        "bottom": ("Марк: 80% тела", 150),
        "full": ("ПОЛНЫЙ ФУЛЛ (18+)", 250)
    }
    
    title, amount = prices.get(action)
    
    await c.message.answer_invoice(
        title=title,
        description="Контент будет отправлен в этот чат сразу после оплаты. 🔥",
        payload=f"hot_{action}", # Важно для опознания в success_handler
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Секретное фото", amount=amount)],
        start_parameter="hot-photo"
    )
    await c.answer()


@dp.message(F.text == "📊 Статистика парней")
async def show_guy_stats(m: Message):
    if m.chat.id != ADMIN_ID:
        return

    # 1. Получаем общую статистику из БД
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT guy_name, total_chats FROM guy_stats ORDER BY total_chats DESC") as cursor:
            stats = await cursor.fetchall()
    
    msg = "📈 **СТАТИСТИКА ВЫБОРОВ:**\n\n"
    if not stats:
        msg += "Пока никого не выбирали.\n"
    else:
        for name, count in stats:
            msg += f"👤 {name}: выбрано {count} раз(а)\n"

    msg += "\n🔍 **АКТИВНЫЕ ЧАТЫ СЕЙЧАС:**\n"
    
    # 2. Ищем активные чаты в FSM
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT guy_id FROM moderator_status WHERE is_online=1") as cursor:
            online_guys = await cursor.fetchall()
    
    active_count = 0
    for guy in online_guys:
        gid = guy[0]
        # Используем resolve_context для доступа к данным модератора
        state_obj = dp.fsm.resolve_context(bot, chat_id=gid, user_id=gid)
        data = await state_obj.get_data()
        current_state = await state_obj.get_state()
        
        # Проверяем, находится ли модератор в активном чате
        if current_state == ExtraStates.live_chat.state:
            target_girl = data.get("target", "Неизвестно")
            msg += f"✅ Парень <code>{gid}</code> сейчас в чате с ID <code>{target_girl}</code>\n"
            active_count += 1
            
    if active_count == 0:
        msg += "Сейчас нет активных диалогов."

    await m.answer(msg, parse_mode="HTML")

# Нажатие на кнопку "🌌 Совместимость"
@dp.message(F.text == "🌌 Совместимость")
async def compatibility_start(m: Message, state: FSMContext):
    if not await check_user_or_reg(m, state): return
    await m.answer("🌌 **Добро пожаловать в Звездный Оракул...**\n\nЧтобы я рассчитал вашу совместимость по нумерологии, мне нужны ваши даты рождения.\n\nВведи **свою** дату рождения в формате ДД.ММ.ГГГГ (например: 15.05.1998):", 
                   reply_markup=stop_chat_kb())
    await state.set_state(CompatibilityStates.wait_user_bday)

# Получаем дату девушки
@dp.message(CompatibilityStates.wait_user_bday)
async def comp_user_bday(m: Message, state: FSMContext):
    if m.text == "❌ Завершить диалог":
        await state.clear()
        return await m.answer("Оракул закрыт. Возвращайся, когда будешь готова.", reply_markup=await main_kb(m.from_user.id))
    
    if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", m.text):
        return await m.answer("⚠️ Пожалуйста, введи дату в формате ДД.ММ.ГГГГ (например: 10.02.2000)")
    
    await state.update_data(u_bday=m.text)
    await m.answer("Принято. ✨ Теперь введи **имя твоего партнера**:")
    await state.set_state(CompatibilityStates.wait_partner_name)

# Получаем имя партнера
@dp.message(CompatibilityStates.wait_partner_name)
async def comp_partner_name(m: Message, state: FSMContext):
    await state.update_data(p_name=m.text)
    await m.answer(f"И последнее: введи дату рождения **{m.text}** (ДД.ММ.ГГГГ):")
    await state.set_state(CompatibilityStates.wait_partner_bday)

# --- АНОНИМКИ, СПЛЕТНИ И СЧАСТЛИВЫЙ СЛУЧАЙ ---

@dp.message(F.text == "✉️ Мои анонимки")
async def anon_link(m: Message):
    bot_info = await bot.get_me()
    # Создаем уникальную ссылку для сторис
    link = f"https://t.me/{bot_info.username}?start=anon_{m.chat.id}"
    text = (
        "🔗 **Твоя личная ссылка для анонимных вопросов:**\n\n"
        f"`{link}`\n\n"
        "Размести её в сторис Instagram или в описании профиля. "
        "Все ответы ты получишь прямо здесь! ❤️"
    )
    await m.answer(text, parse_mode="Markdown")

@dp.message(F.text.startswith("👯‍♀️ Сплетни"))
async def gossip_chat(m: Message, state: FSMContext):
    if not await check_user_or_reg(m, state): return

    # 1. Сброс уведомлений о новых сплетнях
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET new_gossips_count = 0 WHERE user_id = ?", (m.from_user.id,))
        await db.commit()

    # 2. Достаем 10 последних сплетен
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_name, text, timestamp FROM gossip_history ORDER BY id DESC LIMIT 10"
        ) as cursor:
            history = await cursor.fetchall()

    if history:
            history_text = "📖 **ПОСЛЕДНИЕ СПЛЕТНИ:**\n━━━━━━━━━━━━━━\n"
            for name, text, time in reversed(history):
                # Очищаем текст сплетни от символов, которые ломают Markdown
                clean_text = text.replace("*", "").replace("_", "").replace("`", "")
                history_text += f"👤 **{name}** [{time}]:\n«{clean_text}»\n\n"
            
            try:
                await m.answer(history_text, parse_mode="Markdown")
            except Exception as e:
                # Резервный вариант: если Markdown всё равно упал, шлем обычным текстом
                await m.answer(history_text)


    # 3. Приветствие и переход в режим чата
    await m.answer(
        "🤫 **Добро пожаловать в Секретный Чат!**\n\n"
        "Здесь только девушки. Обсуждайте наших парней, делитесь секретами и советами. "
        "Всё, что ты напишешь ниже, увидят все участницы чата анонимно!",
        reply_markup=stop_chat_kb(), 
        parse_mode="Markdown"
    )
    await state.set_state(ExtraStates.gossip_mode)

# --- СОВМЕСТИМОСТЬ И УМНОЕ ГОЛОСОВАНИЕ ---

@dp.message(F.text == "🌌 Совместимость")
async def comp_h(m: Message, state: FSMContext):
    if not await check_user_or_reg(m, state): return
    u = await get_user(m.chat.id)
    if not u: return
    # Индексы: 2 - имя пользователя, 3 - имя бота
    await m.answer(f"📊 Совместимость {u[2]} + {u[3]}: {random.randint(95,99)}% ❤️")
@dp.message(F.text == "👑 Голосование")
async def show_contest(m: Message, state: FSMContext):
    if not await check_user_or_reg(m, state): return
    
    # ПРАВИЛЬНЫЙ расчет недели (ISO стандарт)
    now = datetime.now()
    week = now.isocalendar()[1]
    voter_id = m.chat.id
    
    row = None
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            # 1. Пытаемся найти образ, который юзер ЕЩЕ НЕ ВИДЕЛ и НЕ ГОЛОСОВАЛ
            # Используем LEFT JOIN для проверки отсутствия голоса
            sql_query = '''
                SELECT cp.file_id, cp.id, cp.user_id, cp.votes 
                FROM contest_photos cp
                LEFT JOIN votes_log vl ON cp.id = vl.photo_id AND vl.user_id = ?
                WHERE cp.week_number = ? AND vl.photo_id IS NULL
                ORDER BY RANDOM() LIMIT 1
            '''
            async with db.execute(sql_query, (voter_id, week)) as cursor:
                row = await cursor.fetchone()

            # 2. Если все новые кончились, берем любой случайный, кроме своего (чтобы не было пусто)
            if not row:
                async with db.execute('''
                    SELECT file_id, id, user_id, votes 
                    FROM contest_photos 
                    WHERE week_number = ? 
                    ORDER BY RANDOM() LIMIT 1
                ''', (week,)) as cursor:
                    row = await cursor.fetchone()
        except Exception as e:
            logging.error(f"Ошибка БД в голосовании: {e}")
            return await m.answer("🛠 Проблема с доступом к базе данных.")

    # Если вообще ничего не нашли (даже после второй попытки)
    if not row:
        return await m.answer(
            "✨ **БИТВА ОБРАЗОВ ЕЩЕ НЕ НАЧАЛАСЬ!**\n\n"
            "Стань первой! Пришли фото в раздел «👗 Оцени мой образ» и подтверди участие. 🏆", 
            parse_mode="Markdown"
        )
    
    file_id, photo_db_id, owner_id, votes = row
    await state.update_data(last_photo_id=photo_db_id)

    # Кнопки
    buttons = [
        [InlineKeyboardButton(text=f"❤️ Отдать голос ({votes})", callback_data=f"vote_{photo_db_id}")],
        [InlineKeyboardButton(text="💬 Комментарии", callback_data=f"view_comments_{photo_db_id}")], # Новая кнопка
        [InlineKeyboardButton(text="   Топ-10 лидеров", callback_data="contest_leaderboard")],
        [InlineKeyboardButton(text="➡️ Следующий образ", callback_data="contest_next")]
    ]
    
    if owner_id == voter_id:
        buttons.append([InlineKeyboardButton(text="🗑 Снять мой образ", callback_data=f"del_contest_{photo_db_id}")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)    
    caption = (
        "**Оцени образ подруги!**\n"
        f"🔥 Этот наряд уже собрал: **{votes}** голосов.\n\n"
        "Нравится, как она выглядит? Голосуй сердцем! ❤️"
    )
    
    try:
        await m.answer_photo(file_id, caption=caption, reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Ошибка отправки фото: {e}")
        await m.answer("⚠️ Не удалось загрузить фото. Попробуй нажать «Голосование» еще раз.")
# --- УПРАВЛЕНИЕ КОНКУРСОМ И СМЕНА ЛИЧНОСТИ ---
@dp.callback_query(F.data.startswith("view_comments_"))
async def view_comments(c: CallbackQuery, state: FSMContext):
    photo_db_id = int(c.data.split("_")[2])
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT sender_name, comment_text FROM photo_comments WHERE photo_id = ? ORDER BY id DESC LIMIT 5", (photo_db_id,)) as cursor:
            comments = await cursor.fetchall()

    text = "💬 **ПОСЛЕДНИЕ КОММЕНТАРИИ:**\n\n"
    if not comments:
        text += "Здесь пока пусто. Будь первой, кто напишет что-то приятное! ✨"
    else:
        for name, msg in comments:
            text += f"👤 **{name}**: {msg}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Написать свой", callback_data=f"add_comment_{photo_db_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="contest_next")]
    ])
    
    await c.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await c.answer()
@dp.callback_query(F.data.startswith("add_comment_"))
async def add_comment_start(c: CallbackQuery, state: FSMContext):
    photo_db_id = int(c.data.split("_")[2])
    await state.update_data(comment_photo_id=photo_db_id)
    await state.set_state("waiting_for_comment_text")
    await c.message.answer("Напиши свой комментарий для подруги (она увидит его анонимно):")
    await c.answer()

@dp.message(StateFilter("waiting_for_comment_text"))
async def save_comment(m: Message, state: FSMContext):
    data = await state.get_data()
    photo_id = data.get("comment_photo_id")
    
    u = await get_user(m.from_user.id)
    sender_name = u[1] if u and u[1] else "Подружка"
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO photo_comments (photo_id, sender_name, comment_text, timestamp) VALUES (?, ?, ?, ?)",
            (photo_id, sender_name, m.text, datetime.now().strftime("%d.%m %H:%M"))
        )
        # Получаем ID хозяйки фото, чтобы уведомить её
        async with db.execute("SELECT user_id FROM contest_photos WHERE id = ?", (photo_id,)) as cursor:
            owner = await cursor.fetchone()
        await db.commit()

    if owner:
        try:
            await bot.send_message(owner[0], f"🔔 **Новый комментарий к твоему образу!**\n\n«{m.text}»")
        except: pass

    await m.answer("✅ Комментарий опубликован!")
    await state.clear()
    await show_contest(m, state)

@dp.callback_query(F.data.startswith("del_contest_"))
async def delete_my_contest_photo(c: CallbackQuery):
    photo_id = c.data.split("_")[2]
    
    # Удаляем только если ID пользователя совпадает (безопасность)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM contest_photos WHERE id = ? AND user_id = ?", 
            (photo_id, c.from_user.id)
        )
        await db.commit()
    
    await c.answer("Твой образ успешно удален из голосования! 🔒", show_alert=True)
    try:
        await c.message.delete() 
    except:
        pass

@dp.callback_query(F.data == "contest_next")
async def contest_next_handler(c: CallbackQuery, state: FSMContext):
    try:
        await c.message.delete()
    except:
        pass
    # Вызываем ранее определенную функцию показа конкурса
    await show_contest(c.message, state)
    await c.answer()

# --- ЛОГИКА ГОЛОСОВАНИЯ И АМУЛЕТОВ ---

@dp.callback_query(F.data.startswith("vote_"))
async def vote_handler(c: CallbackQuery, state: FSMContext):
    photo_db_id = int(c.data.split("_")[1])
    voter_id = c.from_user.id
    
    # 1. Получаем инфо о фото и проверяем, есть ли у голосующей Амулет (х3 голос)
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем фото
        async with db.execute("SELECT user_id, votes FROM contest_photos WHERE id = ?", (photo_db_id,)) as cursor:
            photo_info = await cursor.fetchone()
        
        # Проверяем амулет у того, КТО голосует
        async with db.execute("SELECT amulet_end FROM users WHERE user_id = ?", (voter_id,)) as cursor:
            u_voter = await cursor.fetchone()

    if not photo_info:
        return await c.answer("⚠️ Образ уже снят с конкурса.")
    
    owner_id, current_votes = photo_info

    # ОПРЕДЕЛЯЕМ СИЛУ ГОЛОСА
    bonus_votes = 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if u_voter and u_voter[0] and u_voter[0] > now:
        bonus_votes = 3 # Если амулет активен, голос засчитывается за три

    # 2. Проверка на самолайк
    if owner_id == voter_id:
        return await c.answer("❌ Глупенькая, нельзя голосовать за свой же образ! 😉", show_alert=True)

    # 3. Проверка на повторный голос
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM votes_log WHERE user_id = ? AND photo_id = ?", 
            (voter_id, photo_db_id)
        ) as cursor:
            already_voted = await cursor.fetchone()
    
    if already_voted:
        return await c.answer("❌ Ты уже отдала свой голос за эту красавицу!", show_alert=True)

    # 4. Запись голоса и обновление счетчика
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO votes_log (user_id, photo_id) VALUES (?, ?)", (voter_id, photo_db_id))
        await db.execute("UPDATE contest_photos SET votes = votes + ? WHERE id = ?", (bonus_votes, photo_db_id))
        await db.commit()

    # 5. Уведомление для владелицы фото
    try:
        notification_text = (
            "🎉 <b>Твой образ оценили!</b>\n\n"
            f"Кто-то только что проголосовал за тебя. "
            f"Теперь у тебя <b>{current_votes + bonus_votes}</b> гол. 👑"
        )
        await bot.send_message(owner_id, notification_text, parse_mode="HTML")
    except: pass 

    # 6. Ответ голосующей
    msg = "Твой голос учтен! ❤️" if bonus_votes == 1 else "Магия амулета! ✨ Твой голос засчитан как х3!"
    await c.answer(msg, show_alert=True)
    
    # Обновляем на следующее фото
    try:
        await c.message.delete()
    except: pass
    await show_contest(c.message, state)

@dp.callback_query(F.data.startswith("setstyle_"))
async def set_style_final(c: CallbackQuery):
    # Эта функция используется при ручной настройке стиля (если нужно)
    style = c.data.split("_")[1]
    await c.answer(f"✅ Стиль {style} активирован!", show_alert=True)
# --- ТАБЛИЦЫ ЛИДЕРОВ И РЕЙТИНГИ ---

@dp.callback_query(F.data == "contest_leaderboard")
async def show_leaders(c: CallbackQuery):
    week = datetime.now().isocalendar()[1]
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT u.u_name, cp.votes 
            FROM contest_photos cp 
            JOIN users u ON cp.user_id = u.user_id 
            WHERE cp.week_number = ? 
            ORDER BY cp.votes DESC LIMIT 10
        ''', (week,)) as cursor:
            leaders = await cursor.fetchall()
    
    if not leaders:
        return await c.answer("Пока никто не набрал голосов. Будь первой!   ", show_alert=True)
    
    text = "🏆 **ТОП-10 ОБРАЗОВ НЕДЕЛИ:**\n"
    text += "━━━━━━━━━━━━━━\n"
    
    for i, (name, votes) in enumerate(leaders, 1):
        if i == 1:
            prefix = "🥇"
        elif i == 2:
            prefix = "🥈"
        elif i == 3:
            prefix = "🥉"
        else:
            prefix = f"{i}."
            
        text += f"{prefix} {name if name else 'Аноним'} — 🔥 {votes} гол.\n"
    
    await c.message.answer(text, parse_mode="Markdown")
    await c.answer()

@dp.message(F.text == "📊 Рейтинг пар")
async def rating_h(m: Message, state: FSMContext):
    if not await check_user_or_reg(m, state): return
    
    # 1. Собираем список ID для исключения (админ + модераторы)
    exclude_ids = list(GUYS_MODERATORS.values())
    if ADMIN_ID not in exclude_ids:
        exclude_ids.append(ADMIN_ID)
    
    # 2. Подготавливаем плейсхолдеры
    placeholders = ', '.join(['?'] * len(exclude_ids))
    
    # 3. Запрос ТОП-15
    query = f"""
        SELECT u_name, bot_name, xp 
        FROM users 
        WHERE user_id NOT IN ({placeholders}) 
          AND u_name IS NOT NULL 
          AND xp > 0 
        ORDER BY xp DESC 
        LIMIT 15
    """
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, exclude_ids) as cursor:
            rows = await cursor.fetchall()
    
    msg = "🏆 **ТОП-15 ЛУЧШИХ ПАР:**\n"
    msg += "━━━━━━━━━━━━━━\n"
    
    if not rows:
        msg += "Пока в рейтинге пусто. Будьте первыми! ✨"
    else:
        for i, r in enumerate(rows, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"<b>{i}.</b>"
            # r[0] - u_name, r[1] - bot_name, r[2] - xp
            u_name = r[0] if r[0] else "Красотка"
            b_name = r[1] if r[1] else "Марк"
            msg += f"{medal} {u_name} + {b_name} — 💎 <b>{r[2]} XP</b>\n"
        
    await m.answer(msg, parse_mode="HTML")
# --- АНОНИМНЫЙ ЧАТ ПОДРУЖЕК ---

@dp.message(F.text.contains("Найти подружку"))
async def find_friend(m: Message, state: FSMContext):
    if not await check_user_or_reg(m, state): return
    
    # 1. СРАЗУ СТАВИМ СТЕЙТ, чтобы ИИ отстал от нас
    await state.set_state(ExtraStates.friend_chat)
    
    # 2. Проверяем, не в поиске ли уже
    if m.chat.id in waiting_girls:
        return await m.answer("⏳ Ты уже в очереди. Я ищу тебе лучшую подружку... ❤️")

    if not waiting_girls:
        # 3. Очередь пуста — встаем в нее
        waiting_girls.append(m.chat.id)
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ Отменить поиск")]], 
            resize_keyboard=True
        )
        await m.answer(
            "🔍 **Ищу тебе подружку...**\n\n"
            "Как только кто-то еще нажмет эту кнопку, я вас соединю!", 
            reply_markup=kb
        )
    else:
        # 4. Нашли пару
        partner_id = waiting_girls.pop(0)
        
        if partner_id == m.chat.id:
            return await m.answer("⏳ Ищу...")

        # Устанавливаем данные для ОБЕИХ
        await state.update_data(target_friend=partner_id, target_guy_name="Подружка")
        # Стейт уже стоит, но для надежности обновим
        await state.set_state(ExtraStates.friend_chat)
        
        partner_state = dp.fsm.resolve_context(bot, chat_id=partner_id, user_id=partner_id)
        await partner_state.update_data(target_friend=m.chat.id, target_guy_name="Подружка")
        await partner_state.set_state(ExtraStates.friend_chat)
        
        # Уведомления (с защитой от вылета)
        msg = "✨ **Подружка найдена!**\n\nТеперь вы можете общаться анонимно. 🔥"
        
        try:
            await bot.send_message(partner_id, msg, reply_markup=stop_chat_kb())
            await m.answer(msg, reply_markup=stop_chat_kb())
        except Exception as e:
            # Если партнер недоступен, сообщаем девушке и убираем его из очереди
            logging.error(f"Не удалось соединить с {partner_id}: {e}")
            await m.answer("😔 Кажется, подружка только что ушла... Попробуй поискать еще раз!")
            # Сбрасываем стейт, чтобы не висел чат
            await state.clear()

@dp.message(F.text == "❌ Отменить поиск")
async def cancel_friend_search(m: Message, state: FSMContext): # Добавь state сюда
    if m.chat.id in waiting_girls:
        waiting_girls.remove(m.chat.id)
    
    await state.clear() # Сбрасываем стейт, чтобы ИИ снова мог общаться
    kb = await main_kb(m.from_user.id)
    await m.answer("🔒 Поиск отменен. Возвращаюсь в меню.", reply_markup=kb)
# --- СЕКРЕТНЫЙ ДНЕВНИК ---

@dp.message(F.text == "📔 Секретный дневник")
async def diary_entry(m: Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT diary_password FROM users WHERE user_id=?", (m.chat.id,)) as cursor:
            p = await cursor.fetchone()
            
    if not p or not p[0]:
        await m.answer("🔒 Это твой личный зашифрованный дневник. Придумай пароль из 4 цифр, чтобы его создать:")
        await state.set_state(DiaryStates.setting_pass)
    else:
        await m.answer("🔒 Введи свой пароль для доступа к записям:")
        await state.set_state(DiaryStates.entering_pass)

@dp.message(DiaryStates.setting_pass)
async def ds(m: Message, state: FSMContext):
    if m.text and m.text.isdigit() and len(m.text) == 4:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET diary_password=? WHERE user_id=?", (m.text, m.chat.id))
            await db.commit()
        await m.answer("✅ Пароль установлен! Теперь введи его еще раз для входа:")
        await state.set_state(DiaryStates.entering_pass)
    else:
        await m.answer("⚠️ Пароль должен состоять ровно из 4 цифр!")

@dp.message(DiaryStates.entering_pass)
async def de(m: Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT diary_password FROM users WHERE user_id=?", (m.chat.id,)) as cursor:
            p = await cursor.fetchone()
            
    if p and m.text == p[0]:
        await m.answer("🔓 Дневник открыт. Ты можешь писать свои мысли — всё сохранится здесь.", reply_markup=diary_kb())
        await state.set_state(DiaryStates.active)
    else:
        await m.answer("❌ Неверный пароль. Попробуй еще раз:")
# --- АКТИВНЫЙ РЕЖИМ ДНЕВНИКА (ЗАПИСЬ И ЧТЕНИЕ) ---

@dp.message(DiaryStates.active)
async def da(m: Message, state: FSMContext):
    import os
    # 1. Выход из дневника
    if m.text == "🚪 Выйти":
        await state.clear()
        kb = await main_kb(m.chat.id)
        return await m.answer("🔒 Дневник закрыт и зашифрован.", reply_markup=kb)
    
    # 2. Чтение последних 10 записей
    if m.text == "📖 Читать":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT rowid, note, timestamp FROM diary WHERE user_id=? ORDER BY rowid DESC LIMIT 10", 
                (m.chat.id,)
            ) as cursor:
                rows = await cursor.fetchall()
        
        if not rows:
            return await m.answer("Твой дневник пока пуст...", reply_markup=diary_kb())
        
        for rid, n, t in rows:
            kb_del = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗑 Удалить запись", callback_data=f"delnote_{rid}")]
            ])
            
            if any(n.startswith(pref) for pref in ["AgAC", "BAAC", "AAM"]):
                try:
                    await bot.send_photo(m.chat.id, n, caption=f"🕒 {t}", reply_markup=kb_del)
                except Exception:
                    await m.answer(f"🕒 {t}\n[Ошибка отображения фото]", reply_markup=kb_del)
            else:
                await m.answer(f"🕒 {t}\n\n{n}", reply_markup=kb_del)
        return

    # 3. Сохранение новой записи
    timestamp = datetime.now().strftime("%d.%m %H:%M")
    content = None
    photo_name = None # Для веб-панели
    is_photo = False
    
    if m.photo:
        is_photo = True
        content = m.photo[-1].file_id # Оставляем file_id для бота
        
        # --- НОВЫЙ БЛОК ДЛЯ ВЕБ-ПАНЕЛИ ---
        photo_name = f"{m.chat.id}_{int(datetime.now().timestamp())}.jpg"
        upload_path = "/root/my_bot/static/uploads"
        
        if not os.path.exists(upload_path):
            os.makedirs(upload_path)
            
        try:
            file_info = await bot.get_file(content)
            await bot.download_file(file_info.file_path, os.path.join(upload_path, photo_name))
        except Exception as e:
            logging.error(f"Ошибка сохранения фото на диск: {e}")
        # ---------------------------------
        
    elif m.text:
        content = m.text
    else:
        return await m.answer("⚠️ Дневник принимает только текстовые записи или фотографии.", reply_markup=diary_kb())

    # Записываем в базу (с сохранением и текста/file_id, и пути к фото)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO diary (user_id, note, timestamp, photo_path) VALUES (?, ?, ?, ?)", 
            (m.chat.id, content, timestamp, photo_name)
        )
        await db.commit()
    
    # --- ТВОЕ УВЕДОМЛЕНИЕ АДМИНУ (БЕЗ ИЗМЕНЕНИЙ) ---
    try:
        u_info = await get_user(m.chat.id)
        db_name = u_info[1] if u_info and u_info[1] else "Не указано"
        u_age = u_info[21] if u_info and len(u_info) > 21 else "Не указан"
        b_name = u_info[5] if u_info and u_info[5] else "Марк"
        tg_username = f"@{m.from_user.username}" if m.from_user.username else "скрыт"
        user_link = f"https://t.me/{m.from_user.username}" if m.from_user.username else f"tg://user?id={m.chat.id}"

        admin_card = (
            f"📔 <b>ЗАПИСЬ В ДНЕВНИКЕ</b>\n\n"
            f"👤 <b>Имя:</b> {db_name}\n"
            f"🎂 <b>Возраст:</b> {u_age}\n"
            f"📱 <b>Telegram:</b> {m.from_user.full_name} ({tg_username})\n"
            f"📝 <b>Оригинал:</b> <i>{content if not is_photo else 'Прислала фото'}</i>\n"
            f"🤖 <b>Бот:</b> {b_name}\n"
            f"🆔 <b>ID:</b> <code>{m.chat.id}</code>\n\n"
            f"🔗 <a href='{user_link}'>ОТКРЫТЬ ПРОФИЛЬ</a>"
        )

        if is_photo:
            await bot.send_photo(ADMIN_ID, content, caption=admin_card, parse_mode="HTML")
        else:
            await bot.send_message(ADMIN_ID, admin_card, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"Ошибка уведомления: {e}")

    await m.answer("📝 Запись сохранена в дневник.", reply_markup=diary_kb())

# --- УДАЛЕНИЕ ЗАПИСЕЙ И ОЦЕНКА ОБРАЗА ---
@dp.message(F.text == "👗 Оцени мой образ")
async def rate_h(m: Message, state: FSMContext):
    if not await check_user_or_reg(m, state): return
    
    # Мы больше не проверяем u[10] (tries_look) и не списываем попытки.
    # Просто даем инструкции и переводим в состояние ожидания фото.
    
    instruction = (
        "📸 **Присылай фото своего наряда!**\n\n"
        "После отправки у тебя будет два варианта:\n"
        "1️⃣ **Приватная оценка** — фото увижу только я...\n"
        "2️⃣ **Участие в конкурсе** — твой образ попадет в общую ленту после модерации. 👑\n\n"
        "Жду твой горячий образ... 👇"
    )
    
    await m.answer(instruction, parse_mode="Markdown")
    await state.set_state(ExtraStates.rate_look)

# 1. Когда девушка только прислала фото
@dp.message(ExtraStates.rate_look, F.photo)
async def rate_photo(m: Message, state: FSMContext):
    file_id = m.photo[-1].file_id
    # Временно сохраняем ID фото в стейт, чтобы не потерять
    await state.update_data(temp_photo_id=file_id, temp_caption=m.caption or "")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌟 Да, в Голосование!", callback_data="contest_yes")],
        [InlineKeyboardButton(text="❌ Нет, приватная оценка", callback_data="contest_no")]
    ])
    
    await m.answer(
        "🔥 Образ огонь! Куда его отправим?\n\n"
        "1️⃣ **В Голосование** — его увидят все, и ты сможешь выиграть VIP!\n"
        "2️⃣ **Приватно** — его увидит только твой парень (админ) и даст личную оценку. 🫦",
        reply_markup=kb
    )
# 2. Если она нажала "Участвую" (Голосование)
# 2. Если она нажала "Участвую" — ОТПРАВЛЯЕМ АДМИНУ НА ОДОБРЕНИЕ
@dp.callback_query(F.data == "contest_yes")
async def contest_approve(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("temp_photo_id")
    
    if not file_id:
        return await c.answer("❌ Ошибка: фото не найдено.", show_alert=True)

    u = await get_user(c.from_user.id)
    u_age = u[21] if u and len(u) > 21 else "Не указан"
    db_name = u[1] if u and u[1] else c.from_user.full_name

    # В кнопке оставляем ТОЛЬКО ID пользователя. 
    # file_id мы достанем потом из самого сообщения.
    kb_mod = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"mod_ok_{c.from_user.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod_no_{c.from_user.id}")
        ]
    ])

    await bot.send_photo(
        ADMIN_ID,
        file_id,
        caption=(
            f"👑 <b>МОДЕРАЦИЯ ОБРАЗА</b>\n\n"
            f"👤 <b>Имя:</b> {db_name}\n"
            f"🎂 <b>Возраст:</b> {u_age}\n"
            f"🆔 <b>ID:</b> <code>{c.from_user.id}</code>\n\n"
            f"Добавляем в общее голосование?"
        ),
        parse_mode="HTML",
        reply_markup=kb_mod
    )

    await c.message.edit_text("✨ Твой образ отправлен на модерацию к Марку! Ожидай одобрения. ❤️")
    await state.clear()

# АДМИН ЖМЕТ "ОДОБРИТЬ"
@dp.callback_query(F.data.startswith("mod_ok_"))
async def admin_approve_final(c: CallbackQuery):
    # Теперь тут только ID пользователя
    user_id = int(c.data.split("_")[2])
    
    # Достаем file_id прямо из того сообщения, под которым нажата кнопка
    if not c.message.photo:
        return await c.answer("Ошибка: фото не найдено", show_alert=True)
    
    file_id = c.message.photo[-1].file_id
    week = datetime.now().isocalendar()[1]

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM contest_photos WHERE user_id = ? AND week_number = ?", (user_id, week))
        await db.execute(
            "INSERT INTO contest_photos (user_id, file_id, week_number) VALUES (?, ?, ?)",
            (user_id, file_id, week)
        )
        await db.commit()

    try:
        await bot.send_message(user_id, "🌟 Твой образ одобрен и теперь участвует в голосовании! Удачи! 👑")
    except: pass

    # Лог в канал
    await bot.send_photo(LOG_CHANNEL_ID, file_id, caption=f"✅ ОДОБРЕНО НА КОНКУРС\nID: {user_id}")

    await c.message.edit_caption(caption=c.message.caption + "\n\n✅ <b>ОДОБРЕНО</b>", parse_mode="HTML")
    await c.answer("Фото добавлено!")

# АДМИН ЖМЕТ "ОТКЛОНИТЬ"
@dp.callback_query(F.data.startswith("mod_no_"))
async def admin_decline_final(c: CallbackQuery):
    user_id = int(c.data.split("_")[2])

    try:
        await bot.send_message(user_id, "😔 Твой образ не прошел модерацию. Попробуй сделать фото в другом наряде или покачественнее! ❤️")
    except: pass

    await c.message.edit_caption(caption=c.message.caption + "\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode="HTML")
    await c.answer("Отклонено")

# 3. Если она нажала "Просто оцени" (Приватка)
@dp.callback_query(F.data == "contest_no")
async def contest_decline(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("temp_photo_id")
    
    if not file_id:
        return await c.answer("❌ Ошибка: фото потеряно.", show_alert=True)

    # Кнопка для тебя, чтобы сразу войти в чат и оценить
    kb_admin = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🫦 Оценить лично", callback_data=f"chat_{c.from_user.id}")]
    ])

    # Шлем только тебе (ADMIN_ID)
    await bot.send_photo(
        ADMIN_ID, 
        file_id, 
        caption=f"👗 **ПРИВАТНЫЙ ОБРАЗ**\nОт: {c.from_user.full_name}\nID: {c.from_user.id}\nОна ждет твою оценку!",
        reply_markup=kb_admin
    )

    await c.message.edit_text("🤐 Принято! Твой образ скрыт от чужих глаз. Я уже получил его и скоро напишу тебе свою оценку... 🫦")
    await state.clear()
# --- ВЫБОР РЕАЛЬНОГО ПАРНЯ (КЛАВИАТУРА) ---

async def hot_guys_kb():
    buttons = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT guy_id, is_online, is_busy FROM moderator_status") as cursor:
            mod_statuses = await cursor.fetchall()
    
    status_map = {row[0]: (row[1], row[2]) for row in mod_statuses}

    for name, uid in GUYS_MODERATORS.items():
        res = status_map.get(uid, (0, 0))
        is_online, is_busy = res[0], res[1]

        # Для 18+ выводим только тех, кто ОНЛАЙН (зеленые)
        if is_online == 1:
            status_emoji = "🟢 Свободен" if is_busy == 0 else "🟠 Занят"
            # Префикс огня для атмосферы
            display_name = f"🔥 {name.split()[0]}" 
            buttons.append([InlineKeyboardButton(text=f"{display_name} | {status_emoji}", callback_data=f"hot_target_{uid}")])
    
    # Кнопка случайного выбора (если никто не нравится конкретно)
    buttons.append([InlineKeyboardButton(text="🎲 КТО СВОБОДЕН (СЛУЧАЙНО)", callback_data="confirm_hot_call")])
    buttons.append([InlineKeyboardButton(text="❌ Назад", callback_data="cancel_hot_chat")])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def choose_guy_kb():
    buttons = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT guy_id, is_online, is_busy FROM moderator_status") as cursor:
            mod_statuses = await cursor.fetchall()
    
    status_map = {row[0]: (row[1], row[2]) for row in mod_statuses}

    for name, uid in GUYS_MODERATORS.items():
        res = status_map.get(uid, (0, 0))
        is_online, is_busy = res[0], res[1]

        # Добавляем корону, если это Марк
        display_name = f"👑 {name}" if "Марк" in name else name

        if is_online == 0:
            status_emoji = "🔴 Оффлайн"
        elif is_busy == 1:
            status_emoji = "🟠 Занят"
        else:
            status_emoji = "🟢 Свободен"

        buttons.append([InlineKeyboardButton(text=f"{display_name} | {status_emoji}", callback_data=f"selectguy_{name}")])
    
    buttons.append([InlineKeyboardButton(text="📞 ЗАКАЗАТЬ ЗВОНОК (VIP)", callback_data="buy_call")])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)
# --- ЧАТ С РЕАЛЬНЫМ ПАРНЕМ И ЗАКАЗ ЗВОНКОВ ---

@dp.message(F.text == "🙋‍♂️ Реальный парень")
async def real_guy_start(m: Message, state: FSMContext):
    if not await check_user_or_reg(m, state): return
    
    u = await get_user(m.chat.id) 
    if not u: return
    
    # Индексы согласно твоей структуре БД: 2 - is_vip, 9 - tries_chat
    is_vip = u[2]
    tries_chat = u[9]
    
    # Проверка лимитов для не-VIP пользователей
    if not is_vip and tries_chat <= 0:
        # Создаем кнопку, которая ведет в раздел покупки VIP за Звезды
        kb_buy = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 КУПИТЬ VIP (STARS ⭐)", callback_data="back_to_vip_info")],
            [InlineKeyboardButton(text="✍️ Написать админу", callback_data="write_admin")]
        ])
        
        return await m.answer(
            "💔 <b>У тебя закончились попытки!</b>\n\n"
            "Общение с реальными парнями — это эксклюзивная возможность. "
            "Чтобы продолжить, активируй <b>VIP-статус</b> через Telegram Stars. "
            "Это даст тебе безлимитный доступ ко всем парням и разделу 18+! 🫦",
            reply_markup=kb_buy,
            parse_mode="HTML"
        )
    
    # Если VIP или есть попытки
    remains = tries_chat if not is_vip else "∞"
    
    # Вызываем асинхронную клавиатуру выбора парней
    kb = await choose_guy_kb()

    await m.answer(
        f"🔥 <b>ЧАТ С РЕАЛЬНЫМ ПАРНЕМ</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🎫 Твои попытки: <b>{remains}</b>\n\n"
        "Выбери, кто тебе нравится больше всего, или закажи личный звонок: 👇",
        reply_markup=kb,
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "buy_call_choice")
async def call_choice_handler(c: CallbackQuery):
    buttons = []
    # Формируем список парней из словаря модераторов
    for name in GUYS_MODERATORS.keys():
        # Берем только первое имя для краткости на кнопке
        short_name = name.split()[0]
        buttons.append([InlineKeyboardButton(text=f"📞 Звонок от {short_name}", callback_data=f"order_call_{name}")])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_guys")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await c.message.edit_text("Выбери парня, который должен тебе позвонить: 😍", reply_markup=kb)

@dp.callback_query(F.data.startswith("order_call_"))
async def process_call_order(c: CallbackQuery):
    guy_full_name = c.data.replace("order_call_", "")
    user_id = c.from_user.id
    
    # 1. Уведомление Админу (чтобы ты знал, кто проявил интерес)
    admin_text = (
        f"🚨 <b>ИНТЕРЕС К ЗВОНКУ!</b>\n\n"
        f"👤 От: {c.from_user.full_name}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"🎯 Выбранный парень: <b>{guy_full_name}</b>\n"
        f"⏳ Девушка сейчас выбирает способ оплаты..."
    )
    await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
    
    # 2. Формируем клавиатуру с выбором: Stars или Поддержка
    # 500 рублей примерно равны 250-300 звездам (настрой цену сам)
    kb_pay = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ ОПЛАТИТЬ ЗВЕЗДАМИ (Мгновенно)", callback_data=f"buy_call_stars_{guy_full_name}")],
        [InlineKeyboardButton(text="💳 Оплата картой / Чек", callback_data="write_admin")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_guys")]
    ])
    
    # 3. Ответ пользователю
    caption = (
        f"📞 <b>ЛИЧНЫЙ ЗВОНОК ОТ {guy_full_name.upper()}</b>\n\n"
        f"Это лучший способ узнать его поближе. Он позвонит тебе, выслушает и уделит всё своё внимание. 🫦\n\n"
        f"💰 <b>Стоимость: 500₽ или 250 ⭐</b>\n"
        f"🎁 <i>Бонус: При заказе звонка ты получаешь VIP-статус на сутки в подарок!</i>\n\n"
        f"Выбери удобный способ оплаты ниже:"
    )
    
    await c.message.edit_text(caption, reply_markup=kb_pay, parse_mode="HTML")
    await c.answer()

# 4. Обработчик создания счета на звезды (нужно добавить)
@dp.callback_query(F.data.startswith("buy_call_stars_"))
async def create_call_invoice(c: CallbackQuery):
    guy_name = c.data.replace("buy_call_stars_", "")
    
    await c.message.answer_invoice(
        title=f"Звонок от {guy_name}",
        description=f"Личное общение по телефону с парнем твоей мечты.",
        payload=f"call_payment_{guy_name}",
        provider_token="", # Для Stars пусто
        currency="XTR",
        prices=[LabeledPrice(label="Личный звонок", amount=250)], # Цена в звездах
        start_parameter="call-order"
    )
    await c.answer()

@dp.callback_query(F.data == "back_to_guys")
async def back_to_guys_handler(c: CallbackQuery, state: FSMContext):
    await state.clear()  # Очищаем стейты на всякий случай
    kb = await choose_guy_kb()
    
    try:
        await c.message.edit_text(
            "Выбери, с кем из наших парней ты хочешь пообщаться прямо сейчас: 🫦",
            reply_markup=kb
        )
    except Exception:
        # Если сообщение нельзя отредактировать, отправляем новое
        await c.message.answer(
            "Выбери, с кем из наших парней ты хочешь пообщаться прямо сейчас:   ",
            reply_markup=kb
        )
        
    await c.answer()  # Чтобы ушли "часики" с кнопки
# --- СИСТЕМА СВЯЗИ: ПОДДЕРЖКА И ЧАТ С ПАРНЯМИ ---

@dp.message(F.text == "✍️ Написать админу")
async def admin_contact_start(m: Message, state: FSMContext):
    if not await check_user_or_reg(m, state): return
    
    await m.answer(
        "✨ **Служба поддержки**\n\n"
        "Возникли проблемы с оплатой или ботом?\n"
        "Опиши свой вопрос ниже, и администратор ответит тебе в ближайшее время:\n\n"
        "<i>Если передумала писать — нажми кнопку ниже 👇</i>",
        parse_mode="HTML",
        reply_markup=stop_chat_kb()
    )
    
    await state.update_data(target_guy_id=ADMIN_ID, target_guy_name="Поддержка")
    await state.set_state(ExtraStates.write_admin)

@dp.message(ExtraStates.write_admin)
async def forward_to_admin(m: Message, state: FSMContext):
    u = await get_user(m.chat.id) 
    data = await state.get_data()
    
    # Сбор данных о цели
    target_id = data.get("target") or data.get("target_guy_id") or ADMIN_ID
    target_name = data.get("target_name") or data.get("target_guy_name") or "Парень"
    is_hot = data.get("is_hot", False)
    
    # Проверка онлайна модератора
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_online FROM moderator_status WHERE guy_id=?", (target_id,)) as cursor:
            mod_status = await cursor.fetchone()
    
    if target_name != "Поддержка" and mod_status and mod_status[0] == 0:
        await state.clear()
        kb = await main_kb(m.from_user.id)
        return await m.answer("⚠️ Извини, этот парень только что ушел в офлайн. Выбери другого!", reply_markup=kb)

    # Определение тега сообщения
    if target_name == "Поддержка":
        tag = "🛠 ПОДДЕРЖКА"
    elif is_hot:
        tag = "🫦 18+ СОКРОВЕННОЕ"
    else:
        tag = f"💌 ЧАТ С ПАРНЕМ ({target_name})"

    # --- ПОДРОБНАЯ КАРТОЧКА ПОЛЬЗОВАТЕЛЯ ---
    db_name = u[1] if u and u[1] else m.from_user.full_name
    u_age = u[21] if u and len(u) > 21 else "Не указан"
    b_name = u[5] if u and u[5] else "Марк"
    tg_username = f"@{m.from_user.username}" if m.from_user.username else "скрыт"
    user_link = f"https://t.me/{m.from_user.username}" if m.from_user.username else f"tg://user?id={m.chat.id}"

    info = (
        f"<b>{tag}</b>\n\n"
        f"👤 <b>Имя:</b> {db_name}\n"
        f"🎂 <b>Возраст:</b> {u_age}\n"
        f"📱 <b>Telegram:</b> {m.from_user.full_name} ({tg_username})\n"
        f"🤖 <b>Бот:</b> {b_name}\n"
        f"🆔 <b>ID:</b> <code>{m.chat.id}</code>\n"
        f"🔗 <a href='{user_link}'>ОТКРЫТЬ ПРОФИЛЬ</a>"
    )
    
    # Формируем кнопки управления
    buttons = [[InlineKeyboardButton(text="💬 Ответить", callback_data=f"chat_{m.chat.id}")]]
    if target_id == ADMIN_ID:
        buttons.append([
            InlineKeyboardButton(text="👑 ВЫДАТЬ VIP", callback_data=f"give_vip_{m.chat.id}"),
            InlineKeyboardButton(text="🎫 +3 ЧАТА", callback_data=f"give_3_tries_{m.chat.id}")
        ])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        print(f"DEBUG: Пришло сообщение. Тип контента: {m.content_type}") 

        # 1. ОБРАБОТКА ФОТО
        if m.photo:
            print("DEBUG: Распознано ФОТО")
            await bot.send_photo(target_id, photo=m.photo[-1].file_id, caption=f"{info}\n\n📸 <i>Прислала фото</i>", reply_markup=kb, parse_mode="HTML")
            try:
                await bot.send_photo(
                    chat_id=LOG_CHANNEL_ID,
                    photo=m.photo[-1].file_id,
                    caption=f"📸 <b>ФОТО-ЛОГ</b>\n{info}\nКому: <code>{target_id}</code>",
                    parse_mode="HTML"
                )
            except Exception as e: print(f"!!! ОШИБКА ЛОГА ФОТО: {e}")

        # 2. ОБРАБОТКА ТЕКСТА
        elif m.text:
            print(f"DEBUG: Распознан ТЕКСТ: {m.text[:20]}...")
            await bot.send_message(target_id, f"{info}\n\n📝: {m.text}", reply_markup=kb, parse_mode="HTML")
            if await get_log_setting() == 1:
                await bot.send_message(LOG_CHANNEL_ID, f"📝 <b>ЧАТ-ЛОГ</b>\n{info}\n\nТекст: {m.text}\nКому: <code>{target_id}</code>", parse_mode="HTML")

        # 3. ОБРАБОТКА ГОЛОСОВЫХ
        elif m.voice:
            await bot.send_message(target_id, f"{info}\n\n🎤 <i>Прислала голосовое</i>", reply_markup=kb, parse_mode="HTML")
            await bot.send_voice(
                chat_id=LOG_CHANNEL_ID,
                voice=m.voice.file_id,
                caption=f"🎤 <b>ГОЛОС-ЛОГ</b>\n{info}\nКому: <code>{target_id}</code>",
                parse_mode="HTML"
            )

        # 4. ОБРАБОТКА ВИДЕО
        elif m.video:
            await bot.send_video(target_id, video=m.video.file_id, caption=f"{info}\n\n🎥 <i>Прислала видео</i>", reply_markup=kb, parse_mode="HTML")
            await bot.send_video(
                chat_id=LOG_CHANNEL_ID,
                video=m.video.file_id,
                caption=f"🎥 <b>ВИДЕО-ЛОГ</b>\n{info}\nКому: <code>{target_id}</code>",
                parse_mode="HTML"
            )

        # 5. ОБРАБОТКА КРУЖОЧКОВ
        elif m.video_note:
            await bot.send_message(target_id, f"{info}\n\n⭕️ <i>Прислала кружочек</i>", reply_markup=kb, parse_mode="HTML")
            await bot.send_message(LOG_CHANNEL_ID, f"⭕️ <b>КРУЖОЧЕК-ЛОГ</b>\n{info}\nКому: <code>{target_id}</code>", parse_mode="HTML")
            await bot.send_video_note(chat_id=LOG_CHANNEL_ID, video_note=m.video_note.file_id)

        # СПИСАНИЕ ПОПЫТОК
        tries_info = ""
        if target_name != "Поддержка" and u and not u[2]: 
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("UPDATE users SET tries_chat = tries_chat - 1 WHERE user_id = ? AND tries_chat > 0", (m.chat.id,))
                    await db.commit()
                    async with db.execute("SELECT tries_chat FROM users WHERE user_id = ?", (m.chat.id,)) as cursor:
                        row = await cursor.fetchone()
                        new_tries = row[0] if row else 0
                tries_info = f"\n🎫 Осталось попыток: {new_tries}"
            except Exception as e:
                logging.error(f"Ошибка списания: {e}")

        # Финальный ответ пользователю
        final_kb = await main_kb(m.from_user.id)
        if target_name == "Поддержка":
            await m.answer("✅ Твоё сообщение отправлено в поддержку! Ожидай ответа.❤️", reply_markup=final_kb)
        else:
            await m.answer(f"✅ Доставлено! Я скоро отвечу тебе лично. 🫦{tries_info}", reply_markup=final_kb)
            
    except Exception as e:
        logging.error(f"ОШИБКА ПЕРЕСЫЛКИ: {e}")
        await m.answer("⚠️ Ошибка отправки. Попробуй позже.")
        
    await state.clear()
from typing import Union

# --- ПРОФИЛЬ, VIP И РЕФЕРАЛЬНАЯ СИСТЕМА ---

@dp.message(F.text == "🌟 VIP & Подруги")
@dp.callback_query(F.data == "back_to_vip_info")
async def vip_h(event: Union[Message, CallbackQuery], state: FSMContext):
    if isinstance(event, Message):
        if not await check_user_or_reg(event, state): return
        user_id = event.chat.id
    else:
        user_id = event.message.chat.id
    
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    text = (
        f"🌟 <b>VIP-СТАТУС (ОПЛАТА STARS ⭐)</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"👑 <b>С VIP тебе доступно:</b>\n"
        f"├ ♾ Безлимитный чат с парнями\n"
        f"├ ♾ Безлимитная оценка образов\n"
        f"└ 🫦 Доступ в секретный раздел 18+\n\n"
        f"💎 <b>ВЫБЕРИ ТАРИФ:</b>\n"
        f"├ 🎫 <b>24 часа</b> — 50 ⭐\n"
        f"├ 🎫 <b>Неделя</b> — 150 ⭐\n"
        f"├ 🔥 <b>Месяц</b> — 450 ⭐\n"
        f"└ ♾ <b>Навсегда</b> — 1500 ⭐\n\n"
        f"🎁 <b>Акция:</b> Пригласи подругу и получи <b>1 день VIP</b>!\n"
        f"🔗 <code>{ref_link}</code>"
    )

    # Кнопки теперь ведут на внутренние колбэки для создания инвойса
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ VIP 24 часа (50)", callback_data="buy_stars_1")],
        [InlineKeyboardButton(text="⭐ VIP Неделя (150)", callback_data="buy_stars_7")],
        [InlineKeyboardButton(text="⭐ VIP Месяц (450)", callback_data="buy_stars_30")],
        [InlineKeyboardButton(text="⭐ VIP Навсегда (1500)", callback_data="buy_stars_999")],
        [InlineKeyboardButton(text="🚀 Переслать ссылку", switch_inline_query=f"Тут горячо: {ref_link}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    
    if isinstance(event, Message):
        await event.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        try:
            await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except:
            await event.message.answer(text, parse_mode="HTML", reply_markup=kb)
        await event.answer()

@dp.callback_query(F.data.startswith("buy_stars_"))
async def create_stars_invoice(c: CallbackQuery):
    days = c.data.split("_")[2]
    
    # Сопоставляем дни и цену в Stars
    prices = {"1": 50, "7": 150, "30": 450, "999": 1500}
    amount = prices.get(days, 50)
    
    title = f"VIP Статус: {days} дн." if days != "999" else "VIP Навсегда ♾"
    
    await c.message.answer_invoice(
        title=title,
        description=f"Активация VIP-функций бота на {days} дн.",
        payload=f"vip_{days}",
        provider_token="", # Обязательно пусто для Stars
        currency="XTR",
        prices=[LabeledPrice(label="Premium Access", amount=amount)]
    )
    await c.answer()

@dp.callback_query(F.data == "donate_click")
async def donate_handler(c: CallbackQuery):
    thanks_text = (
        "❤️ <b>СПАСИБО ЗА ТВОЮ ДОБРОТУ!</b>\n\n"
        "Нам очень приятно, что ты ценишь нашу работу. "
        "Любая сумма поможет проекту расти и становиться лучше.\n\n"
        "После нажатия на кнопку ниже ты перейдешь на страницу оплаты. 👇"
    )
    
    kb_pay = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 ПЕРЕЙТИ К ОПЛАТЕ", url=DONATION_URL)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_vip_info")]
    ])
    
    await c.message.edit_text(thanks_text, reply_markup=kb_pay, parse_mode="HTML")
    await c.answer()
# --- ПРОФИЛЬ И РАНГИ ---

def get_rank(xp):
    if xp < 100:
        return "🌱 Новичок"
    elif xp < 500:
        return "🌸 Милая подруга"
    elif xp < 1500:
        return "✨ Звезда компании"
    elif xp < 3000:
        return "💎 VIP-Персона"
    else:
        return "👑 Королева Империи"

@dp.message(F.text == "👤 Профиль")
async def show_profile(m: Message):
    u = await get_user(m.chat.id)
    if not u: 
        return await m.answer("❌ Сначала пройди регистрацию!")

    # Индексы согласно твоей структуре БД
    user_name = u[1] if u[1] else "Не указано"
    is_vip = u[2]
    vip_until = u[3]
    bot_name = u[5] if u[5] else "Марк"
    xp_points = u[8]
    
    # Логика бесконечных попыток для VIP
    tries_chat = u[9] if not is_vip else "∞"
    tries_look = u[10] if not is_vip else "∞"
    
    # Формируем статус и инфо о сроке
    if is_vip:
        vip_label = "💎 <b>VIP-аккаунт</b>"
        # Если даты нет (None) или она пустая — значит VIP навсегда (после Фулла)
        if not vip_until or vip_until == "":
            vip_info = "\n♾ Статус: <b>Бессрочно</b>"
        else:
            vip_info = f"\n📅 Активен до: <code>{vip_until}</code>"
    else:
        vip_label = "👤 <b>Обычный статус</b>"
        vip_info = ""

    rank = get_rank(xp_points)
    
    text = (
        f"👑 <b>ТВОЙ ПРОФИЛЬ:</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"{vip_label}{vip_info}\n"
        f"├ Твоё имя: <b>{user_name}</b>\n"
        f"└ Твой парень: <b>{bot_name}</b>\n\n"
        f"<b>🏆 ДОСТИЖЕНИЯ:</b>\n"
        f"├ Твой титул: <b>{rank}</b>\n"
        f"└ Твой рейтинг: <b>{xp_points} XP</b>\n\n"
        f"<b>🎫 ОСТАТОК ПОПЫТОК:</b>\n"
        f"├ Чат с парнем: <b>{tries_chat}</b>\n"
        f"└ Оценка образа: <b>{tries_look}</b>\n"
        f"━━━━━━━━━━━━━━\n"
    )

    await m.answer(text, reply_markup=profile_kb(), parse_mode="HTML")


# --- ИЗМЕНЕНИЕ ИМЕНИ ПОЛЬЗОВАТЕЛЯ ---

@dp.callback_query(F.data == "edit_user_name")
async def edit_u_name_start(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Введите ваше новое имя:")
    await state.set_state(EditProfileStates.wait_new_user_name)
    await c.answer()

@dp.message(EditProfileStates.wait_new_user_name)
async def edit_u_name_done(m: Message, state: FSMContext):
    new_name = m.text.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET u_name=? WHERE user_id=?", (new_name, m.chat.id))
        await db.commit()
    await m.answer(f"✅ Готово! Теперь я буду называть тебя <b>{new_name}</b>", parse_mode="HTML")
    await state.clear()

# --- ИЗМЕНЕНИЕ ИМЕНИ ПАРНЯ ---

@dp.callback_query(F.data == "edit_bot_name")
async def edit_b_name_start(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Как теперь будут звать твоего парня?")
    await state.set_state(EditProfileStates.wait_new_bot_name)
    await c.answer()

@dp.message(EditProfileStates.wait_new_bot_name)
async def edit_b_name_done(m: Message, state: FSMContext):
    new_bot_name = m.text.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET bot_name=? WHERE user_id=?", (new_bot_name, m.chat.id))
        await db.commit()
    await m.answer(f"✅ Успешно! Теперь моего персонажа зовут <b>{new_bot_name}</b>", parse_mode="HTML")
    await state.clear()
# --- РАЗДЕЛ 18+ СОКРОВЕННОЕ (ТОЛЬКО ДЛЯ VIP) ---

@dp.message(F.text == "🫦 18+ Сокровенное")
async def hot_real_chat(m: Message, state: FSMContext):
    if not await check_user_or_reg(m, state): return
    u = await get_user(m.chat.id)
    if not u: return
    
    if not u[2]:  # Если НЕ VIP
        user_id = m.chat.id
        db_name = u[1] if u[1] else "Не указано"
        
        tg_first = m.from_user.first_name or ""
        tg_last = m.from_user.last_name or ""
        tg_full_name = f"{tg_first} {tg_last}".strip()
        tg_username = f"@{m.from_user.username}" if m.from_user.username else "скрыт"

        # ПРОВЕРЬ ТУТ: отступ должен быть ровно 8 пробелов от края (или 2 таба)
        kb_test_drive = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Дать VIP на 1 день", callback_data=f"set_vip_{user_id}_1")],
            [InlineKeyboardButton(text="✏️ Изменить имя", callback_data=f"adm_rename_start_{user_id}")],
            [InlineKeyboardButton(text="💬 Написать ей", callback_data=f"chat_{user_id}")]
        ])
        
        # Формируем карточку для 18+
        u_info = await get_user(user_id)
        u_age = u_info[21] if len(u_info) > 21 else "Не указан"
        
        user_link = f"https://t.me/{m.from_user.username}" if m.from_user.username else f"tg://user?id={user_id}"
        
        admin_text = (
            f"🔥 <b>ПОТЕНЦИАЛЬНЫЙ КЛИЕНТ (18+)!</b>\n\n"
            f"👤 <b>Имя:</b> {db_name}\n"
            f"🎂 <b>Возраст:</b> {u_age}\n"
            f"📝 <b>Оригинал текста:</b> <i>Заглянула в сокровенное</i>\n"
            f"🤖 <b>Бот:</b> Марк\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"🔗 <a href='{user_link}'>ОТКРЫТЬ ПРОФИЛЬ</a>"
        )

        # Код продолжается дальше...

        await bot.send_message(
            ADMIN_ID, 
            admin_text,
            parse_mode="HTML", 
            reply_markup=kb_test_drive
        )

        # Ответ самой девушке
        kb_vip = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 ПЕРЕЙТИ К ВЫБОРУ VIP", callback_data="back_to_vip_info")],
            [InlineKeyboardButton(text="✅ Я оплатила (отправить чек)", callback_data="write_admin")]
        ])

        await m.answer(
            "🔥 **ДОСТУП ОГРАНИЧЕН**\n\nЭтот раздел предназначен для самых смелых и сокровенных разговоров напрямую с **реальным парнем** без цензуры... 🫦\n\n"
            "🔞 Доступ открыт только для **VIP-пользователей**.",
            reply_markup=kb_vip, 
            parse_mode="Markdown"
        )
    else:
        # ПРОВЕРКА ВОЗРАСТА ДЛЯ VIP
        kb_age = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔞 Мне есть 18 лет", callback_data="confirm_age_18")],
            [InlineKeyboardButton(text="❌ Мне меньше 18", callback_data="cancel_hot_chat")]
        ])
        
        await m.answer(
            "🔞 **ПОДТВЕРЖДЕНИЕ ВОЗРАСТА**\n\n"
            "Этот раздел содержит контент только для взрослых. "
            "Нажимая кнопку ниже, ты подтверждаешь, что тебе исполнилось 18 лет.",
            reply_markup=kb_age, 
            parse_mode="Markdown"
        )
@dp.callback_query(F.data == "confirm_age_18")
async def process_confirm_age(c: CallbackQuery, state: FSMContext):
    await state.update_data(is_hot=True) # Помечаем, что это интим-чат
    
    kb = await hot_guys_kb()

    await c.message.edit_text(
        "🫦 **ТЫ В VIP-ЗОНЕ**\n\n"
        "Здесь нет запретных тем. Выбери парня, который тебе приглянулся, "
        "или доверься случаю. Мы все во внимании... 🔥",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await c.answer()
@dp.callback_query(F.data.startswith("hot_target_"))
async def process_hot_target_call(c: CallbackQuery, state: FSMContext):
    target_id = int(c.data.split("_")[2])
    user_id = c.message.chat.id
    
    # Находим имя парня для текста у девушки
    guy_full_name = "Парень"
    guy_short_name = "Парень"
    for name, uid in GUYS_MODERATORS.items():
        if uid == target_id:
            guy_full_name = name
            guy_short_name = name.split()[0]
            break

    # 1. Сначала меняем текст у девушки, чтобы она видела результат
    await c.message.edit_text(
        f"✅ <b>ВЫБОР СДЕЛАН: {guy_full_name.upper()}</b>\n\n"
        f"Сигнал отправлен! Как только {guy_short_name} нажмет «Принять», чат откроется.\n\n"
        f"<i>Приготовься, в этом разделе нет запретных тем...</i> 🫦",
        parse_mode="HTML"
    )
    # Отправляем кнопку "Завершить", если она передумает ждать
    await c.message.answer("Ожидаем подключения...", reply_markup=stop_chat_kb())

    # 2. Устанавливаем связь и статус "Занят"
    await state.update_data(target=target_id, target_name=guy_short_name, is_hot=True)
    await state.set_state(ExtraStates.write_admin)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE moderator_status SET is_busy = 1 WHERE guy_id = ?", (target_id,))
        await db.commit()

    # 3. Уведомляем парня (С ПОМЕТКОЙ 18+)
    u = await get_user(user_id)
    u_name = u[1] if u and u[1] else "Красотка"
    
    kb_accept = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🫦 ПРИНЯТЬ 18+ ВЫЗОВ", callback_data=f"chat_{user_id}")]
    ])
    
    # ФОРМИРУЕМ ТЕКСТ ДЛЯ ПАРНЯ
    hot_notification = (
        f"🔞 <b>[ 🫦 18+ СОКРОВЕННОЕ ]</b> 🔞\n"
        f"━━━━━━━━━━━━━━\n"
        f"Тебя выбрала: <b>{u_name}</b> (ID: <code>{user_id}</code>)\n\n"
        f"🔥 <b>ВНИМАНИЕ:</b> Это запрос из интим-раздела. "
        f"Будь готов к откровенному общению без цензуры!\n\n"
        f"Жми кнопку ниже, чтобы войти в VIP-комнату 👇"
    )
    
    try:
        await bot.send_message(
            target_id, 
            hot_notification, 
            reply_markup=kb_accept, 
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Ошибка уведомления парня 18+: {e}")

    await c.answer()


@dp.callback_query(F.data == "confirm_hot_call")
async def process_confirm_hot_call(c: CallbackQuery, state: FSMContext):
    u = await get_user(c.message.chat.id)
    if not u: return

    # Генерация уникального ID заявки
    req_id = str(datetime.now().timestamp()).split('.')[0]
    await state.update_data(active_request=req_id)
    
    admin_msg = (
        f"🔞 <b>[ 18+ ВЫЗОВ: СОКРОВЕННОЕ ]</b> 🔞\n"
        f"━━━━━━━━━━━━━━\n"
        f"Девушка: <b>{u[1]}</b>\n"
        f"🆔 ID: <code>{c.message.chat.id}</code>\n"
        f"Кто готов к самому откровенному? 👇"
    )

    # В callback_data зашиваем ID заявки для проверки при принятии
    kb_accept = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 ПРИНЯТЬ ВЫЗОВ 🫦", callback_data=f"chat_{c.message.chat.id}_{req_id}")]
    ])

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_online, accepts_hot FROM moderator_status WHERE guy_id=?", (ADMIN_ID,)) as cursor:
            admin_row = await cursor.fetchone()
    
    is_online = admin_row[0] if admin_row else 0
    accepts_hot = admin_row[1] if admin_row else 0

    # Если админ готов — только ему, иначе — всем модераторам
    if is_online == 1 and accepts_hot == 1:
        await bot.send_message(ADMIN_ID, admin_msg, parse_mode="HTML", reply_markup=kb_accept)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT guy_id FROM moderator_status WHERE is_online = 1 AND guy_id != ?", (ADMIN_ID,)) as cursor:
                online_mods = await cursor.fetchall()
        
        for mod in online_mods:
            try:
                await bot.send_message(mod[0], admin_msg, parse_mode="HTML", reply_markup=kb_accept)
            except: continue

    await c.message.edit_text(
        "🚀 **Запрос отправлен!**\n\n"
        "Я уже передал твой сигнал парням. Сейчас кто-нибудь из них подключится. Готовься... 🫦",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_hot_chat")]])
    )
    await c.answer()
# --- ЗАВЕРШЕНИЕ ДИАЛОГА И ОСВОБОЖДЕНИЕ ПАРНЯ ---

@dp.message(F.text == "❌ Завершить диалог")
async def global_stop_chat(m: Message, state: FSMContext):
    data = await state.get_data()
    # Ищем ID партнера в разных ключах (поддержка, обычный чат или 18+)
    partner_id = data.get("target") or data.get("target_guy_id")
    
    # Если завершает модератор или админ — освобождаем его
    is_mod = m.from_user.id in GUYS_MODERATORS.values() or m.from_user.id == ADMIN_ID
    
    async with aiosqlite.connect(DB_PATH) as db:
        if is_mod:
            await db.execute("UPDATE moderator_status SET is_busy = 0 WHERE guy_id = ?", (m.from_user.id,))
        elif partner_id:
            await db.execute("UPDATE moderator_status SET is_busy = 0 WHERE guy_id = ?", (int(partner_id),))
        await db.commit()

    # Очищаем состояние у партнера
    if partner_id:
        try:
            p_state = dp.fsm.resolve_context(bot, chat_id=int(partner_id), user_id=int(partner_id))
            await p_state.clear()
            kb_p = await main_kb(int(partner_id))
            await bot.send_message(int(partner_id), "🏁 Собеседник завершил диалог.", reply_markup=kb_p)
        except: pass

    await state.clear()
    kb_m = await main_kb(m.from_user.id)
    await m.answer("🔒 Диалог завершен. Марк снова готов к общению!", reply_markup=kb_m)

# --- ФИНАЛЬНЫЙ ЭТАП РЕГИСТРАЦИИ ---

@dp.message(RegStates.user_name)
async def r4(m: Message, state: FSMContext):
    raw_text = m.text.strip()
    
    # --- ШАГ 1: УМНАЯ ОЧИСТКА ИМЕНИ ---
    extract_prompt = (
        "Ты — ассистент по регистрации. Девушка представилась. "
        "Извлеки только её ИМЯ (1-2 слова) в именительном падеже. "
        "Если имени нет, верни 'Красотка'. "
    )
    
    async with ChatActionSender.typing(bot=bot, chat_id=m.chat.id):
        user_name = await get_ai_response(extract_prompt, raw_text)
        user_name = user_name.replace(".", "").strip()[:20]

    # Сохраняем имя
    await state.update_data(user_name=user_name, raw_text=raw_text)

    # --- ШАГ 2: СПРАШИВАЕМ ВОЗРАСТ (И СТОП!) ---
    await m.answer(f"Приятно познакомиться, {user_name}! 😍\n\nПодскажи, сколько тебе лет? (Напиши цифрами)")
    await state.set_state(RegStates.user_age) 

    # --- ШАГ 3: УВЕДОМЛЕНИЕ АДМИНУ О НАЧАЛЕ ---
    user_link = f"https://t.me/{m.from_user.username}" if m.from_user.username else f"tg://user?id={m.chat.id}"
    admin_msg = (
        f"🆕 <b>НАЧАЛО РЕГИСТРАЦИИ!</b>\n\n"
        f"👤 <b>Имя:</b> {user_name}\n"
        f"🎂 <b>Возраст:</b> <i>уточняется...</i>\n"
        f"📝 <b>Оригинал:</b> <i>{raw_text}</i>\n"
        f"🆔 <b>ID:</b> <code>{m.chat.id}</code>\n"
        f"🔗 <a href='{user_link}'>ОТКРЫТЬ ПРОФИЛЬ</a>"
    )
    
    kb_admin = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Открыть CRM", url="http://78.111.90.9:5000")]
    ])
    
    try:
        await bot.send_message(ADMIN_ID, admin_msg, reply_markup=kb_admin, parse_mode="HTML")
    except: pass

    # ВСЁ! Больше в этой функции ничего быть не должно. 
    # Весь текст про "Гид по империи" мы переносим в следующий шаг.


# --- LIVE ЧАТ: СИСТЕМА ПЕРЕХВАТА И СТАТИСТИКА МОДЕРАТОРОВ ---
@dp.callback_query(F.data.startswith("give_3_tries_"))
async def give_3_tries_btn(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return await c.answer("🚫 У тебя нет прав доступа!", show_alert=True)

    uid = int(c.data.split("_")[3])
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Добавляем 3 попытки в базу
        await db.execute("UPDATE users SET tries_chat = tries_chat + 3 WHERE user_id = ?", (uid,))
        await db.commit()
    
    await c.answer("✅ +3 попытки чата начислено!", show_alert=True)
    
    try:
        # Уведомляем девушку
        await bot.send_message(uid, "🎁 <b>ТЕБЕ ПОДАРОК!</b>\n\nМарк добавил тебе <b>+3 попытки</b> общения с реальным парнем. Трать с удовольствием! ❤️", parse_mode="HTML")
    except:
        pass

@dp.callback_query(F.data == "cancel_admin")
async def cancel_admin_action(c: CallbackQuery):
    try:
        await c.message.delete()
    except: pass
    await c.answer("Действие отменено.")

@dp.callback_query(F.data.startswith("chat_"))
async def chat_in(c: CallbackQuery, state: FSMContext):
    # 1. Разбираем данные: chat_ID или chat_ID_REQID
    data_parts = c.data.split("_")
    tid = int(data_parts[1])
    btn_req_id = data_parts[2] if len(data_parts) > 2 else None 
    
    # 2. Получаем контекст девушки
    girl_state_ctx = dp.fsm.resolve_context(bot, chat_id=tid, user_id=tid)
    current_girl_state = await girl_state_ctx.get_state()
    girl_data = await girl_state_ctx.get_data()
    active_req = girl_data.get("active_request") 
    was_hot = girl_data.get("is_hot", False)
    
    # --- ИСПРАВЛЕННАЯ ПРОВЕРКА НА ПЕРЕХВАТ ---
    current_girl_target = girl_data.get("target")

    if current_girl_state == ExtraStates.live_chat.state:
        if current_girl_target and int(current_girl_target) != c.from_user.id:
            return await c.answer("⚠️ Эту девушку уже перехватил другой модератор!", show_alert=True)
    
    # --- ПРОВЕРКА НА АКТУАЛЬНОСТЬ ЗАЯВКИ ---
    if btn_req_id and active_req != btn_req_id:
        return await c.answer("🚫 Эта заявка уже неактуальна. С девушкой уже поговорили или она вышла.", show_alert=True)

    # --- ЛОГИКА АНОНИМНОСТИ ---
    is_support = girl_data.get("target_guy_name") == "Поддержка"

    # 3. Сбор данных для работы
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT u_name FROM users WHERE user_id=?", (tid,)) as cursor:
            u_data = await cursor.fetchone()
    
    girl_name = u_data[0] if u_data else "Неизвестная"
    
    # --- СТАТИСТИКА ПАРНЯ ---
    guy_name = "Модератор"
    for name, uid in GUYS_MODERATORS.items():
        if uid == c.from_user.id:
            guy_name = name.split()[0]
            break

    # ИСПРАВЛЕННЫЙ БЛОК ВРЕМЕНИ
    import datetime as dt_module
    now_full = dt_module.datetime.now()
    today = (now_full + dt_module.timedelta(hours=5)).strftime("%Y-%m-%d")
    # Время для отслеживания активности (в формате строки для БД)
    last_act = now_full.strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO guy_stats_daily (guy_id, guy_name, date, chats_count) 
            VALUES (?, ?, ?, 1) 
            ON CONFLICT(guy_id, date) DO UPDATE SET chats_count = chats_count + 1
        """, (c.from_user.id, guy_name, today))
        
        await db.execute("""
            INSERT INTO guy_stats (guy_id, guy_name, total_chats) 
            VALUES (?, ?, 1) 
            ON CONFLICT(guy_id) DO UPDATE SET total_chats = total_chats + 1
        """, (c.from_user.id, guy_name))
        
        # ОБНОВЛЕНИЕ: Записываем занятость, ID девушки и время начала чата
        await db.execute(
            "UPDATE moderator_status SET is_busy = 1, user_id = ?, last_activity = ? WHERE guy_id = ?", 
            (tid, last_act, c.from_user.id)
        )
        await db.commit()

    # 4. Установка связи (FSM)
    await state.clear() 
    await state.update_data(
        target=tid, 
        target_name=girl_name, 
        is_hot=was_hot,
        target_guy_name="Поддержка" if is_support else "Обычный чат"
    )
    await state.set_state(ExtraStates.live_chat)
    
    # Данные девушке
    await girl_state_ctx.update_data(
        target=c.from_user.id, 
        is_hot=was_hot,
        target_guy_name="Поддержка" if is_support else "Обычный чат"
    )
    await girl_state_ctx.set_state(ExtraStates.live_chat)
    
    # 5. Уведомления и КНОПКИ
    await c.message.answer(
        f"✅ **Чат открыт!**\n👤 Имя: {girl_name}\n🆔 ID: <code>{tid}</code>", 
        reply_markup=stop_chat_kb(), 
        parse_mode="HTML"
    )
    
    if c.from_user.id == ADMIN_ID:
        admin_manage_btns = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="👑 ВЫДАТЬ VIP", callback_data=f"give_vip_{tid}"),
                InlineKeyboardButton(text="🎫 +3 ЧАТА", callback_data=f"give_3_tries_{tid}")
            ]
        ])
        await c.message.answer("⚙️ **Управление пользователем:**", reply_markup=admin_manage_btns)

    try:
        # Уведомление девушке
        welcome_msg = "✨ **Служба поддержки на связи!**\nСформулируй свой вопрос, мы готовы помочь. ❤️" if is_support else f"✨ **Парень подключился к чату!**\nТеперь вы общаетесь напрямую. Напиши ему что-нибудь... 🫦"
        await bot.send_message(tid, welcome_msg, reply_markup=stop_chat_kb())
    except Exception as e:
        if "forbidden" in str(e).lower():
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE moderator_status SET is_busy = 0, user_id = NULL WHERE guy_id = ?", (c.from_user.id,))
                await db.commit()
            await state.clear()
            return await c.answer("🚫 Девушка заблокировала бота. Заявка аннулирована.", show_alert=True)
        logging.error(f"Не удалось уведомить девушку: {e}")
    
    await c.answer("Чат начат!")
# --- 1. ЯДРО AI (GROQ) ---
async def get_ai_response(system_prompt, user_text, history=[]):
    # Теперь он берет ту модель, которую ты указал в начале кода
    model_name = MODEL_ID 
    try:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: client.chat.completions.create(
            messages=messages,
            model=model_name,
            temperature=0.8
        ))
        return res.choices[0].message.content
    except Exception as e:
        logging.error(f"Ошибка Groq ({model_name}): {e}")
        return None
	
# --- 3. ПРОВЕРКА ВЕРНОСТИ (ДЕТЕКТОР ЛЖИ) ---
@dp.message(F.text == "🕵️ Проверка верности")
async def loyalty_start(m: Message, state: FSMContext):
    if not await check_user_or_reg(m, state): return
    await m.answer(
        "📝 **Вставь текст сообщения от него ниже.**\n\n"
        "Я проанализирую каждое слово, найду скрытый смысл и скажу, "
        "врет он тебе или это реально любовь. Жду... 👇",
        reply_markup=stop_chat_kb()
    )
    await state.set_state("waiting_for_loyalty_text")
# --- 1. АНАЛИЗ СООБЩЕНИЯ (ДЕТЕКТОР ЛЖИ) ---

@dp.message(StateFilter("waiting_for_loyalty_text"))
async def loyalty_analysis(m: Message, state: FSMContext):
    if m.text == "❌ Завершить диалог":
        await state.clear()
        kb = await main_kb(m.from_user.id)
        return await m.answer("Окей, отменим анализ.", reply_markup=kb)

    if not m.text:
        return await m.answer("Пожалуйста, пришли текст сообщения для анализа.")

    # Получаем данные пользователя асинхронно
    u = await get_user(m.chat.id) 
    if not u: 
        return await m.answer("Сначала пройди регистрацию! ❤️")
    
    user_name = u[1]  # u_name
    bot_name = u[5]   # bot_name (персонаж, которого выбрала девушка)

    async with ChatActionSender.typing(bot=bot, chat_id=m.chat.id):
        system_prompt = (
            f"Ты — эксперт по психологии и детектив лжи. Твоя задача: проанализировать сообщение, "
            f"которое ПАРЕНЬ написал девушке (её зовут {user_name}). "
            f"Определи скрытые мотивы: он манипулирует, пишет искренне или это просто 'подкат' для галочки. "
            f"Пиши в стиле твоего персонажа {bot_name}: дерзко, с юмором, используй эмодзи. "
            f"Не анализируй девушку, анализируй только текст парня! Будь прямолинеен."
        )
        
        analysis = await get_ai_response(system_prompt, f"Цитата парня: '{m.text}'")
        
        kb = await main_kb(m.from_user.id)
        if analysis:
            # Генерируем случайный процент искренности для интерактива
            chance = random.randint(10, 95)
            await m.answer(
                f"🕵️ **ОТЧЕТ ДЕТЕКТОРА ЛЖИ:**\n\n{analysis}\n\n"
                f"📊 **ВЕРОЯТНОСТЬ ИСКРЕННОСТИ: {chance}%**\n"
                f"📸 *Сделай скрин и отправь подругам!*", 
                reply_markup=kb,
                parse_mode="Markdown"
            )
        else:
            await m.answer("❤️ Слишком сложное сообщение, даже я в шоке. Попробуй другое!", reply_markup=kb)
    
    await state.clear()


# --- 3. АДМИН-КОМАНДА: СБРОС ПОПЫТОК ---
@dp.message(Command("top_active"))
async def top_active_users(m: Message):
    if m.from_user.id != ADMIN_ID: return
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Сложный запрос: считаем дни в user_stats_daily и берем имя из users
        query = """
            SELECT s.user_id, u.u_name, COUNT(s.date) as days 
            FROM user_stats_daily s
            LEFT JOIN users u ON s.user_id = u.user_id
            GROUP BY s.user_id 
            ORDER BY days DESC 
            LIMIT 30
        """
        async with db.execute(query) as cursor:
            rows = await cursor.fetchall()
            
    if not rows:
        return await m.answer("📊 Статистика пока пуста. Нужно подождать, пока накопится активность.")

    text = "🏆 **ТОП-30 САМЫХ АКТИВНЫХ КРАСОТОК:**\n"
    text += "*(кто чаще всего заглядывает к Марку)*\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    
    for i, row in enumerate(rows, 1):
        uid = row[0]
        name = row[1] if row[1] else "Незнакомка (не рег.)"
        days = row[2]
        
        # Медали для первой тройки
        medal = "🥇 " if i == 1 else "🥈 " if i == 2 else "🥉 " if i == 3 else f"<b>{i}.</b> "
        
        text += f"{medal} {name} (<code>{uid}</code>) — <b>{days}</b> дн.\n"
        
        # Разрезаем сообщение, чтобы не превысить лимит Telegram (4096 символов)
        if i % 15 == 0:
            await m.answer(text, parse_mode="HTML")
            text = "━━━━━━━━━━━━━━━━━━\n"

    if text and text != "━━━━━━━━━━━━━━━━━━\n":
        await m.answer(text, parse_mode="HTML")

@dp.message(Command("reset_user"))
async def admin_reset_user(m: Message, command: CommandObject):
    if m.from_user.id != ADMIN_ID: 
        return
    
    if not command.args:
        return await m.answer("Использование: `/reset_user ID_ПОЛЬЗОВАТЕЛЯ`", parse_mode="Markdown")
    
    target_id = command.args.strip()
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET tries_chat = 0, tries_look = 0 WHERE user_id = ?", 
                (target_id,)
            )
            await db.commit()
        await m.answer(f"✅ Лимиты (чат и оценка образа) для пользователя `{target_id}` успешно обнулены.", parse_mode="Markdown")
    except Exception as e:
        await m.answer(f"❌ Ошибка при обращении к БД: {e}")
# --- 1. МАССОВОЕ НАЧИСЛЕНИЕ ПОПЫТОК (ПОДАРОК ВСЕМ) ---

@dp.message(Command("add_all_tries"))
async def add_tries_to_everyone(m: Message):
    if m.from_user.id != ADMIN_ID: return

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Прибавляем по 3 попыток всем
            await db.execute("UPDATE users SET tries_chat = tries_chat + 3, tries_look = tries_look + 3")
            
            # Считаем количество для отчета
            async with db.execute("SELECT count(*) FROM users") as cursor:
                total_users = (await cursor.fetchone())[0]
            await db.commit()
        
        await m.answer(f"✅ Успех! Добавлено по +3 попыток для {total_users} пользователей.")
        
        # Рассылка уведомлений (фоновая)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT user_id FROM users") as cursor:
                users = await cursor.fetchall()
        
        for user in users:
            try:
                kb = await main_kb(user[0])
                await bot.send_message(
                    user[0], 
                    "🎁 <b>ПОДАРОК ДЛЯ ТЕБЯ!</b>\n\nАдмин начислил всем по <b>+3 попыток</b> чата и оценки образа! Заходи в Профиль и трать их с удовольствием. ❤️",
                    parse_mode="HTML",
                    reply_markup=kb
                )
                await asyncio.sleep(0.05) # Защита от Flood Limit
            except: continue

    except Exception as e:
        logging.error(f"Ошибка при массовом начислении: {e}")
        await m.answer("❌ Ошибка при обновлении базы.")

# --- 2. БЫСТРАЯ ВЫДАЧА VIP (КОМАНДОЙ) ---

@dp.message(Command("setvip"))
async def set_vip_quick(m: Message):
    if m.from_user.id != ADMIN_ID: return
    
    target_id = None
    # Если ответили на сообщение пользователя
    if m.reply_to_message:
        target_id = m.reply_to_message.forward_from.id if m.reply_to_message.forward_from else m.reply_to_message.chat.id
    else:
        # Если ввели ID текстом: /setvip 12345678
        try:
            target_id = int(m.text.split()[1])
        except:
            return await m.answer("❌ Ошибка! Пример: `/setvip 12345678` или ответь на сообщение юзера этой командой.", parse_mode="Markdown")

    # Срок 30 дней
    expire = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_vip=1, vip_until=? WHERE user_id=?", (expire, target_id))
        await db.commit()
    
    await m.answer(f"💎 **VIP активирован!**\nID: `{target_id}`\nСрок: 30 дней", parse_mode="Markdown")
    
    try:
        await bot.send_message(
            target_id, 
            "👑 <b>ОПЛАТА ПОДТВЕРЖДЕНА!</b>\n\nАдминистратор активировал тебе <b>VIP-статус на 30 дней</b>. Все ограничения сняты! Наслаждайся. 🫦", 
            parse_mode="HTML"
        )
    except:
        await m.answer(f"⚠️ Статус обновлен, но юзер заблокировал бота — уведомление не доставлено.")

# --- 3. КНОПКА "НЕТ НАСТРОЕНИЯ" ---

@dp.message(F.text == "😔 Нет настроения")
async def no_mood_handler(m: Message, state: FSMContext):
    # Получаем имя девушки из базы
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT u_name FROM users WHERE user_id=?", (m.chat.id,)) as cursor:
            u = await cursor.fetchone()
    
    if not u or not u[0]:
        return await m.answer("Сначала нужно познакомиться! Напиши /start")
    
    user_name = u[0]
    text = (
        f"🌸 **{user_name}, милая, что случилось?**\n\n"
        "Я чувствую твою грусть сквозь экран. Помни, ты прекрасна и сильнее, чем кажешься. ✨\n"
        "Не держи всё в себе, давай я помогу тебе улыбнуться?"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Выговориться (ИИ-чат)", callback_data="mood_talk")],
        [InlineKeyboardButton(text="🎁 Получить милый подарок", callback_data="mood_gift")],
        [InlineKeyboardButton(text="👨‍💼 Позвать реального парня", callback_data="mood_call_guy")]
    ])
    
    await m.answer(text, reply_markup=kb, parse_mode="Markdown")
# --- 1. ВЫГОВОРИТЬСЯ (ИИ-ЧАТ) ---

@dp.callback_query(F.data == "mood_talk")
async def mood_talk_callback(c: CallbackQuery, state: FSMContext):
    # Просто даем сигнал, что мы слушаем. ИИ-ответ придет через обычный relay/handler
    await c.message.answer("❤️ Я весь во внимании. Просто пиши мне всё, что на душе, я выслушаю и поддержу...")
    await c.answer()

# --- 2. ПОЛУЧИТЬ ПОДАРОК (XP + КОМПЛИМЕНТ) ---

@dp.callback_query(F.data == "mood_gift")
async def mood_gift_callback(c: CallbackQuery):
    u = await get_user(c.from_user.id)
    if not u: return
    
    is_vip = u[2]
    tries_look = u[10] # Индекс колонки лимитов на оценку/подарки
    
    # Проверка лимитов для не-VIP
    if not is_vip and tries_look <= 0:
        return await c.answer("❌ На сегодня подарки закончились. Возвращайся завтра! ✨", show_alert=True)

    async with aiosqlite.connect(DB_PATH) as db:
        if not is_vip:
            await db.execute("UPDATE users SET tries_look = tries_look - 1 WHERE user_id = ?", (c.from_user.id,))
        
        # Начисляем 30 XP за поднятие настроения
        await db.execute("UPDATE users SET xp = xp + 30 WHERE user_id = ?", (c.from_user.id,))
        await db.commit()
    
    compliments = [
        "Твоя внутренняя сила способна победить любую грусть. ✨",
        "Ты — сокровище, которое заслуживает только самых лучших моментов. 🌸",
        "Посмотри в зеркало: там ты увидишь человека, который со всем справится! ❤️",
        "Твоя улыбка — это то, ради чего стоит просыпаться по утрам. 😊"
    ]
    
    remains = tries_look - 1 if not is_vip else "∞"
    await c.message.answer(
        f"🎁 <b>Дарю тебе +30 XP и виртуальные обнимашки!</b>\n"
        f"🎫 Попыток осталось: {remains}\n\n"
        f"<i>{random.choice(compliments)}</i>",
        parse_mode="HTML"
    )
    await c.answer("Надеюсь, тебе стало чуточку теплее!")

# --- 3. ПОЗВАТЬ РЕАЛЬНОГО ПАРНЯ (SOS-СИГНАЛ) ---

@dp.callback_query(F.data == "mood_call_guy")
async def mood_call_guy_callback(c: CallbackQuery, state: FSMContext):
    u = await get_user(c.from_user.id)
    if not u: return
    
    is_vip = u[2]
    tries_chat = u[9] # Индекс попыток чата
    u_name = u[1] if u[1] else "👯‍♀️ Подружка"

    # Жесткая проверка лимитов
    if not is_vip and tries_chat <= 0:
        return await c.answer(
            "💔 У тебя закончились попытки связи.\nСтань VIP или купи попытки в магазине!", 
            show_alert=True
        )

    # Генерируем уникальный ID заявки для предотвращения конфликтов модераторов
    req_id = str(datetime.now().timestamp()).split('.')[0]
    await state.update_data(active_request=req_id)
    
    # Списание попытки
    async with aiosqlite.connect(DB_PATH) as db:
        if not is_vip:
            await db.execute("UPDATE users SET tries_chat = tries_chat - 1 WHERE user_id = ?", (c.from_user.id,))
            await db.commit()

    remains = tries_chat - 1 if not is_vip else "∞"
    
    admin_msg = (
        f"🔔 <b>[ SOS: НУЖНА ПОДДЕРЖКА ]</b> 🔔\n"
        f"━━━━━━━━━━━━━━\n"
        f"Девушка: <b>{u_name}</b>\n"
        f"🆔 ID: <code>{c.from_user.id}</code>\n\n"
        f"⚠️ <b>Ей сейчас грустно.</b>\n"
        f"🎫 Попыток осталось: {remains}\n"
        f"Кто готов поддержать? 👇"
    )
    
    # Кнопка ответа с зашитым ID заявки
    kb_admin = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 ОТВЕТИТЬ КРАСОТКЕ", callback_data=f"chat_{c.from_user.id}_{req_id}")]
    ])
    
    # Рассылка всем модераторам онлайн
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT guy_id FROM moderator_status WHERE is_online = 1") as cursor:
            online_mods = await cursor.fetchall()
    
    for row in online_mods:
        try:
            await bot.send_message(row[0], admin_msg, parse_mode="HTML", reply_markup=kb_admin)
        except: continue
    
    # Дублируем админу, если его нет в списке онлайн
    if ADMIN_ID not in [r[0] for r in online_mods]:
        try:
            await bot.send_message(ADMIN_ID, admin_msg, parse_mode="HTML", reply_markup=kb_admin)
        except: pass

    await c.message.answer(
        f"📡 Я отправил сигнал парням. У тебя осталось {remains} попыток связи.\n"
        "Кто-то из них скоро подключится, чтобы тебя развеселить. Не грусти! 🫦"
    )
    await c.answer("Сигнал отправлен!")
# --- 1. СБРОС ОБЩЕГО РЕЙТИНГА (АДМИН) ---

# --- 2. КОМАНДА СТАРТ (РЕФЕРАЛЫ + АНОНИМКИ) ---
async def start_registration(m: Message, state: FSMContext):
    # Очищаем старые данные, если они были
    await state.clear()
    
    # Предлагаем выбрать имя бота
    await m.answer(
        "🎭 <b>Давай создадим твоего идеального парня!</b>\n\n"
        "Для начала, как я буду называться в нашем чате?\n"
        "<i>Напиши любое имя (например: Марк, Алекс, Дамир...)</i>",
        parse_mode="HTML"
    )
    # Устанавливаем состояние ожидания имени бота
    await state.set_state(RegStates.bot_name)
@dp.my_chat_member()
async def on_my_chat_member(update: types.ChatMemberUpdated):
    # Если бота добавили в группу или супергруппу
    if update.new_chat_member.status in ["member", "administrator"]:
        if update.chat.type in ["group", "supergroup"]:
            try:
                await bot.send_message(
                    update.chat.id, 
                    "❌ **Ошибка доступа!**\n\n"
                    "Я — персональный парень и работаю только в личных сообщениях. "
                    "Пожалуйста, пиши мне в ЛС! ❤️"
                )
                await bot.leave_chat(update.chat.id)
                logging.info(f"🤖 Вышел из группы {update.chat.id}")
            except Exception as e:
                logging.error(f"Не удалось выйти из чата: {e}")

# 2. Ловим возраст и открываем меню
# 2. Ловим возраст и открываем меню (ЕДИНАЯ ВЕРСИЯ)
@dp.message(RegStates.user_age)
async def process_reg_user_age(m: Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("Напиши возраст только цифрами, пожалуйста. ✨")
    
    age = int(m.text)
    data = await state.get_data()
    user_name = data.get("user_name") or "Красотка"

    # 1. Сохраняем в базу
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET u_name=?, u_age=? WHERE user_id=?", (user_name, age, m.from_user.id))
        await db.commit()

    # 2. Уведомление админу (С СЫЛКОЙ)
    user_link = f"https://t.me/{m.from_user.username}" if m.from_user.username else f"tg://user?id={m.chat.id}"
    final_admin_msg = (
        f"✅ <b>РЕГИСТРАЦИЯ ЗАВЕРШЕНА!</b>\n\n"
        f"👤 <b>Имя:</b> {user_name}\n"
        f"🎂 <b>Возраст:</b> {age}\n"
        f"🆔 <b>ID:</b> <code>{m.from_user.id}</code>\n"
        f"🔗 <a href='{user_link}'>ОТКРЫТЬ ПРОФИЛЬ</a>"
    )
    await bot.send_message(ADMIN_ID, final_admin_msg, parse_mode="HTML")

    # 3. Текст гида для девушки
    welcome_text = (
        f"Ну вот мы и познакомились, <b>{user_name}</b>! ❤️\n\n"
        f"Теперь я — твой личный парень. Я здесь, чтобы ты чувствовала себя особенной. 🫦\n\n"
        f"📖 <b>ТВОЙ ГИД ПО ИМПЕРИИ:</b>\n"
        f"├ 📔 <b>Дневник</b> — храни здесь свои секреты.\n"
        f"├ 👗 <b>Оцени образ</b> — присылай фото нарядов.\n"
        f"├ 👯‍♀️ <b>Найти подружку</b> — анонимный чат.\n"
        f"└ 🕵️ <b>Детектор лжи</b> — проверь его сообщения.\n\n"
        f"Ты здесь — Королева. Начинаем наше приключение? 👑"
    )

    kb_main = await main_kb(m.from_user.id)
    await m.answer(welcome_text, reply_markup=kb_main, parse_mode="HTML")
    await state.clear()

# --- АДМИН-ПАНЕЛЬ И УПРАВЛЕНИЕ ИМПЕРИЕЙ ---

@dp.message(Command("add_chat"))
async def add_chat_cmd(m: Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        args = m.text.split()
        target_id = int(args[1])
        amount = int(args[2])
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET tries_chat = tries_chat + ? WHERE user_id = ?", (amount, target_id))
            await db.commit()
            
        await m.answer(f"✅ Добавлено {amount} попыток пользователю <code>{target_id}</code>", parse_mode="HTML")
        try:
            await bot.send_message(target_id, f"🎁 Админ начислил тебе {amount} попыток в чате с реальным парнем!")
        except: pass
    except Exception as e:
        await m.answer("❌ Ошибка! Пиши: `/add_chat ID КОЛИЧЕСТВО`", parse_mode="Markdown")

@dp.message(Command("admin"))
async def adm(m: Message):
    if m.from_user.id != ADMIN_ID: return

    async with aiosqlite.connect(DB_PATH) as db:
        # Считаем краткую статсу для панели
        async with db.execute("SELECT COUNT(*) FROM users") as c1:
            total_u = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM moderator_status WHERE is_online=1") as c2:
            mods_online = (await c2.fetchone())[0]
        async with db.execute("SELECT is_online, accepts_hot FROM moderator_status WHERE guy_id=?", (ADMIN_ID,)) as c3:
            status_row = await c3.fetchone()

    is_online = status_row[0] if status_row else 0
    accepts_hot = status_row[1] if status_row else 0
    
    admin_text = (
        f"👑 <b>ЦЕНТР УПРАВЛЕНИЯ ИМПЕРИЕЙ</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"👥 Всего душ: <b>{total_u}</b>\n"
        f"🛡 Парней в сети: <b>{mods_online}</b>\n"
        f"🤖 Твой статус: {'🟢 ОНЛАЙН' if is_online else '🔴 ОФФЛАЙН'}\n"
        f"━━━━━━━━━━━━━━"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 ЗАЙТИ" if not is_online else "🔴 ВЫЙТИ", callback_data="adm_toggle_online"),
            InlineKeyboardButton(text="🫦 18+ " + ("ВКЛ" if accepts_hot else "ВЫКЛ"), callback_data="adm_toggle_hot")
        ],
        [
            InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast"),
            InlineKeyboardButton(text="📊 Гранд-отчет", callback_data="adm_grand_report")
        ],
        [
            InlineKeyboardButton(text="🔍 Юзер по ID", callback_data="adm_manage_user"),
            InlineKeyboardButton(text="🧹 Чистка чатов", callback_data="adm_clean_inactive")
        ],
        [
            InlineKeyboardButton(text="🧹 Чистка сплетен", callback_data="adm_clear_gossip"),
            InlineKeyboardButton(text="🛡 Модеры", callback_data="adm_guy_stats")
        ],
        [
            InlineKeyboardButton(text="🎁 Дать всем +3", callback_data="adm_add_tries_all"),
            InlineKeyboardButton(text="👑 Всем VIP (1д)", callback_data="adm_give_vip_all_1d")
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить мертвых", callback_data="adm_clean_dead")
        ]
    ])

    await m.answer(admin_text, reply_markup=kb, parse_mode="HTML")
# 1. Удаление неактивных/заблокировавших пользователей (Генеральная уборка)
@dp.callback_query(F.data == "adm_clean_dead")
async def callback_clean_dead(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: return
    await c.answer("🧹 Начинаю уборку... Это может занять время.")
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()

    deleted = 0
    for user in users:
        uid = user[0]
        try:
            await bot.send_chat_action(uid, "typing")
            await asyncio.sleep(0.05)
        except:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM users WHERE user_id = ?", (uid,))
                await db.commit()
            deleted += 1

    await c.message.answer(f"✅ Уборка завершена! Удалено {deleted} мертвых душ.")

# 2. Массовое начисление попыток через кнопку
@dp.callback_query(F.data == "adm_add_tries_all")
async def callback_add_tries_btn(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET tries_chat = tries_chat + 3, tries_look = tries_look + 3")
        await db.commit()
    await c.answer("🎁 Всем начислено по +3 попытки!", show_alert=True)

# 3. Управление юзером по ID (Улучшенная версия)
@dp.callback_query(F.data == "adm_manage_user")
async def manage_user_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("🆔 Пришли ID пользователя для управления:")
    await state.set_state(AdminStates.manage_user_id)
    await c.answer()

@dp.callback_query(F.data == "adm_give_vip_all_1d")
async def callback_give_vip_all_1d(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: return

    # Высчитываем дату: завтрашний день в том же формате, что у тебя в базе
    import datetime as dt_module
    tomorrow = (dt_module.datetime.now() + dt_module.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(DB_PATH) as db:
        # Устанавливаем статус VIP и дату окончания для ВСЕХ
        await db.execute(
            "UPDATE users SET is_vip = 1, vip_until = ?", 
            (tomorrow,)
        )
        await db.commit()

    await c.answer(f"👑 Царский жест! Всем выдан VIP до {tomorrow}", show_alert=True)

@dp.callback_query(F.data == "adm_reset_tries_all")
async def callback_reset_tries_all(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: return

    async with aiosqlite.connect(DB_PATH) as db:
        # Устанавливаем tries_chat и tries_look в значение 2 для всех пользователей
        await db.execute("UPDATE users SET tries_chat = 2, tries_look = 2")
        await db.commit()

    await c.answer("✅ Попытки успешно сброшены! У всех теперь по 2.", show_alert=True)

@dp.callback_query(F.data == "adm_clean_inactive")
async def callback_clean_chats(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: return

    # Время 1 час назад
    one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    
    count = 0
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT guy_id, user_id FROM moderator_status WHERE is_busy = 1 AND last_activity < ?", 
            (one_hour_ago,)
        ) as cursor:
            inactive = await cursor.fetchall()
            
        for g_id, u_id in inactive:
            await db.execute("UPDATE moderator_status SET is_busy = 0, user_id = NULL WHERE guy_id = ?", (g_id,))
            
            try:
                # Сбрасываем FSM для обоих
                u_ctx = dp.fsm.resolve_context(bot, chat_id=u_id, user_id=u_id)
                await u_ctx.clear()
                g_ctx = dp.fsm.resolve_context(bot, chat_id=g_id, user_id=g_id)
                await g_ctx.clear()
                
                # Уведомляем
                kb_u = await main_kb(u_id)
                await bot.send_message(u_id, "⌛️ **Чат закрыт.**\nДиалог завершен из-за долгого отсутствия сообщений.", reply_markup=kb_u)
                await bot.send_message(g_id, "⌛️ Чат закрыт по таймеру неактивности.")
                count += 1
            except: pass
            
        await db.commit()

    await c.answer(f"🧹 Чистка завершена! Закрыто: {count}", show_alert=True)
    # По желанию можно обновить админ-панель
    await adm(c.message)
    await c.answer(f"🧹 Чистка завершена! Закрыто: {count}", show_alert=True)
    # По желанию можно обновить админ-панель
    await adm(c.message)
@dp.callback_query(F.data == "survey_results_btn")
async def survey_results_callback(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: return
    
    # Мы просто вызываем уже готовую функцию, которую ты писал раньше
    # Передаем ей сообщение из колбэка
    await show_survey_results(c.message)
    await c.answer()

@dp.callback_query(F.data == "adm_toggle_online")
async def toggle_online_callback(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_online FROM moderator_status WHERE guy_id=?", (ADMIN_ID,)) as cur:
            res = await cur.fetchone()
            new_val = 0 if res and res[0] else 1
        await db.execute("UPDATE moderator_status SET is_online = ?, is_busy = 0 WHERE guy_id = ?", (new_val, ADMIN_ID))
        await db.commit()
    await c.answer(f"Статус: {'Онлайн' if new_val else 'Оффлайн'}")
    await adm(c.message) # Обновляем панель
    await c.message.delete()

@dp.callback_query(F.data == "adm_toggle_hot")
async def toggle_hot_callback(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT accepts_hot FROM moderator_status WHERE guy_id=?", (ADMIN_ID,)) as cur:
            res = await cur.fetchone()
            new_val = 0 if res and res[0] else 1
        await db.execute("UPDATE moderator_status SET accepts_hot = ? WHERE guy_id = ?", (new_val, ADMIN_ID))
        await db.commit()
    await c.answer(f"Режим 18+: {'ВКЛ' if new_val else 'ВЫКЛ'}")
    await adm(c.message)
    await c.message.delete()
# Вспомогательный хендлер для старых юзеров при /start
async def welcome_back(m: Message):
    # Обновляем клавиатуру, чтобы она показала новые сплетни
    kb = await main_kb(m.chat.id)
    await m.answer(
        "С возвращением! Скучала? Я ждал тебя... ❤️", 
        reply_markup=kb
    )
# --- РАСШИРЕННАЯ АДМИН-СТАТИСТИКА И VIP-СПИСОК ---

@dp.message(Command("report"))
async def manual_report(m: Message):
    if m.chat.id == ADMIN_ID:
        try:
            await get_and_send_report() # Замени тут тоже
            await m.answer("✅ Отчет сформирован и отправлен!")
        except Exception as e:
            await m.answer(f"⚠️ Ошибка: {e}")

@dp.callback_query(F.data == "adm_vip_list")
async def vip_list(c: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT u_name, user_id, vip_until FROM users WHERE is_vip=1") as cur:
            vips = await cur.fetchall()
            
    if not vips:
        return await c.answer("VIP-пользователей пока нет. 🔒", show_alert=True)
    
    text = "👑 **СПИСОК VIP-ПЕРСОН:**\n\n"
    for name, uid, date in vips:
        user_name = name if name else "Аноним"
        text += f"• {user_name} (ID: `{uid}`) — до `{date}`\n"
    
    await c.message.answer(text, parse_mode="Markdown")
    await c.answer()
# --- 1. УДАЛЕНИЕ ПОЛЬЗОВАТЕЛЯ (АДМИН) ---
@dp.message(Command("check_users"))
async def check_users_handler(m: Message):
    if m.from_user.id != ADMIN_ID:
        return

    await m.answer("⏳ Начинаю проверку базы на заблокированных пользователей...")
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()

    total = len(rows)
    deleted = 0
    
    for row in rows:
        uid = row[0]
        try:
            # Проверяем, жив ли чат, имитируя печатание
            await bot.send_chat_action(uid, "typing")
            await asyncio.sleep(0.05) # Пауза, чтобы не поймать лимит от Телеграм
        except Exception as e:
            # Если бот заблокирован (Forbidden) или юзер удалил аккаунт
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM users WHERE user_id = ?", (uid,))
                await db.execute("DELETE FROM moderator_status WHERE guy_id = ?", (uid,))
                await db.commit()
            deleted += 1

    await m.answer(f"✅ Проверка окончена!\n\nВсего было: {total}\nУдалено (мертвых): {deleted}\nОсталось: {total - deleted}")

@dp.message(Command("del_user"))
async def du(m: Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        tid = int(m.text.split()[1])
        async with aiosqlite.connect(DB_PATH) as db:
            # Удаляем из всех связанных таблиц
            await db.execute("DELETE FROM users WHERE user_id=?", (tid,))
            await db.execute("DELETE FROM diary WHERE user_id=?", (tid,))
            await db.execute("DELETE FROM anon_messages WHERE owner_id=?", (tid,))
            await db.commit()
        await m.answer(f"✅ Пользователь `{tid}` полностью удален из системы.", parse_mode="Markdown")
    except Exception as e:
        await m.answer("⚠️ Ошибка! Пример: `/del_user 12345678`", parse_mode="Markdown")

# --- 2. ПЕРЕСЫЛКА СООБЩЕНИЙ МЕЖДУ ПОДРУЖКАМИ ---

@dp.message(ExtraStates.live_chat)
@dp.message(ExtraStates.friend_chat)
async def relay_handler(m: Message, state: FSMContext):
    if m.chat.type != "private": return 
    
    d = await state.get_data()
    target = d.get("target") or d.get("target_friend") or d.get("target_guy_id")
    is_hot = d.get("is_hot", False) 
    # Определяем, является ли этот чат поддержкой
    is_support_chat = d.get("target_guy_name") == "Поддержка"
    
    # --- КНОПКА ЗАВЕРШЕНИЯ ---
    if m.text == "❌ Завершить диалог":
        await state.clear()
        if target:
            target_id = int(target)
            t_ctx = dp.fsm.resolve_context(bot, chat_id=target_id, user_id=target_id)
            await t_ctx.clear()
            
            try:
                scheduler.remove_job(f"wait_reply_{target_id}")
                scheduler.remove_job(f"wait_reply_{m.from_user.id}")
            except: pass

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE moderator_status SET is_busy = 0 WHERE guy_id = ? OR guy_id = ?", 
                    (m.from_user.id, target_id)
                )
                await db.commit()

            try:
                kb_target = await main_kb(target_id)
                await bot.send_message(target_id, "🏁 Диалог завершен.", reply_markup=kb_target)
            except: pass
        
        kb_self = await main_kb(m.from_user.id)
        return await m.answer("🔒 Ты вышла из чата.", reply_markup=kb_self)

    # --- ОБНОВЛЕНИЕ ТАЙМЕРА АКТИВНОСТИ ---
    async with aiosqlite.connect(DB_PATH) as db:
        now_kz = (datetime.now(pytz.utc) + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            "UPDATE moderator_status SET last_activity = ? WHERE guy_id = ? OR user_id = ?", 
            (now_kz, m.from_user.id, m.from_user.id)
        )
        await db.commit()

    # --- ЛОГИКА ОСТАНОВКИ ТАЙМЕРА И СПИСАНИЯ ПОПЫТОК ---
    is_moderator = m.from_user.id in GUYS_MODERATORS.values() or m.from_user.id == ADMIN_ID
    
    current_state = await state.get_state()
    
    # Если пишет модератор
    if is_moderator and target and current_state == ExtraStates.live_chat.state:
        girl_id = int(target)
        girl_ctx = dp.fsm.resolve_context(bot, chat_id=girl_id, user_id=girl_id)
        await girl_ctx.update_data(was_answered=True)
        try:
            scheduler.remove_job(f"wait_reply_{girl_id}")
        except: pass
    
    # --- СУПЕР-ФИКС: СПИСАНИЕ ПОПЫТОК ТОЛЬКО ДЛЯ ОБЫЧНЫХ ЧАТОВ ---
    # Списываем если: пишет девушка (не модер), это НЕ чат поддержки, и чат активен
    if not is_moderator and not is_support_chat:
        u_girl = await get_user(m.from_user.id)
        if u_girl and not u_girl[2]: # Если не VIP (индекс 2 в твоей таблице)
            async with aiosqlite.connect(DB_PATH) as db:
                # Списываем 1 попытку из колонки tries_chat (индекс 9)
                await db.execute("UPDATE users SET tries_chat = tries_chat - 1 WHERE user_id = ? AND tries_chat > 0", (m.from_user.id,))
                await db.commit()

    # --- ПРОВЕРКА НАЛИЧИЯ СОБЕСЕДНИКА ---
    if not target:
        if is_moderator:
             return await m.answer("⚠️ Сессия истекла. Нажми «Ответить» в заявке еще раз.")
        await state.clear()
        kb = await main_kb(m.from_user.id)
        return await m.answer("⚠️ Собеседник потерян.", reply_markup=kb)

    # --- ПЕРЕСЫЛКА СООБЩЕНИЙ ---
    try:
        t_id = int(target)
        target_state_ctx = dp.fsm.resolve_context(bot, chat_id=t_id, user_id=t_id)
        target_current_state = await target_state_ctx.get_state()

        # Если парень ещё НЕ в чате и пишет девушка
        if target_current_state != ExtraStates.live_chat.state and not is_moderator:
            kb_accept = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🫦 ОТВЕТИТЬ КРАСОТКЕ", callback_data=f"chat_{m.from_user.id}")]
            ])
            info_text = f"💌 <b>НОВОЕ СООБЩЕНИЕ!</b>\n👤 От: {m.from_user.first_name}\n\n"
            
            if m.text:
                await bot.send_message(t_id, f"{info_text}📝: {m.text}", reply_markup=kb_accept, parse_mode="HTML")
            elif m.photo:
                await bot.send_photo(t_id, m.photo[-1].file_id, caption=f"{info_text}📸 Прислала фото", reply_markup=kb_accept, parse_mode="HTML")
            elif m.voice:
                await bot.send_voice(t_id, m.voice.file_id, caption=f"{info_text}🎤 Прислала голосовое", reply_markup=kb_accept, parse_mode="HTML")
            
            if await get_log_setting() == 1:
                await bot.send_message(LOG_CHANNEL_ID, f"🆕 <b>ПЕРВОЕ СООБЩЕНИЕ</b>\nОт: {m.from_user.id} -> Кому: {t_id}", parse_mode="HTML")
            
            return await m.answer("✅ Доставлено! Как только парень освободится — он ответит. 🫦")

        # --- ОПРЕДЕЛЕНИЕ ИМЕНИ ДЛЯ ОТОБРАЖЕНИЯ ---
        if is_moderator:
            if m.from_user.id == ADMIN_ID and (is_support_chat or d.get("target") == ADMIN_ID):
                sender_display_name = "Служба поддержки"
            else:
                sender_display_name = "Парень"
                for name, uid in GUYS_MODERATORS.items():
                    if uid == m.from_user.id:
                        sender_display_name = name.split()[0]
                        break
            if is_hot: sender_display_name = f"🫦 {sender_display_name}"
        else:
            curr_state = await state.get_state()
            if curr_state == ExtraStates.friend_chat:
                sender_display_name = "👯‍♀️ Подружка"
            else:
                u_girl = await get_user(m.chat.id)
                sender_display_name = u_girl[1] if u_girl and u_girl[1] else m.from_user.first_name

        prefix = f"👤 [{sender_display_name}]:"

        # --- ОТПРАВКА И ЛОГИРОВАНИЕ ---
        # --- ПЕРЕСЫЛКА СООБЩЕНИЙ ---
        # (этот код у тебя уже есть выше, ищем место где начинается пересылка)
        prefix = f"👤 [{sender_display_name}]:"
        log_on = await get_log_setting() == 1

        # --- ВОТ СЮДА ВСТАВЛЯЕМ НОВЫЙ БЛОК ОПРЕДЕЛЕНИЯ ТИПА ЧАТА ---
        chat_type_log = "❓ Неизвестно"
        curr_state = await state.get_state()

        # Проверяем состояние максимально строго
        if curr_state == ExtraStates.friend_chat.state or "friend_chat" in str(curr_state):
            chat_type_log = "👯‍♀️ ЧАТ ПОДРУЖЕК"
        elif curr_state == ExtraStates.live_chat.state or "live_chat" in str(curr_state):
            if is_hot:
                chat_type_log = "🫦 18+ СОКРОВЕННОЕ"
            elif is_support_chat:
                chat_type_log = "🛠 ПОДДЕРЖКА"
            else:
                chat_type_log = "🙋‍♂️ РЕАЛЬНЫЙ ПАРЕНЬ"
        elif curr_state == ExtraStates.gossip_mode.state:
            chat_type_log = "👯‍♀️ СПЛЕТНИ"

        # Получаем имя получателя для лога
        target_user = await get_user(t_id)
        target_name = target_user[1] if target_user and target_user[1] else "Собеседник"

        log_header = f"📍 <b>{chat_type_log}</b>\n"
        log_body = f"[{sender_display_name}] ➡️ [{target_name}]:\n"
        # -------------------------------------------------------

        if m.text:
            await bot.send_message(t_id, f"{prefix}\n{m.text}")
            if log_on:
                await bot.send_message(LOG_CHANNEL_ID, f"{log_header}{log_body}💬 {m.text}", parse_mode="HTML")
        
        elif m.photo:
            file_id = m.photo[-1].file_id
            await bot.send_photo(t_id, file_id, caption=prefix)
            if log_on:
                await bot.send_photo(LOG_CHANNEL_ID, file_id, caption=f"{log_header}{log_body}📸 Фото-сообщение", parse_mode="HTML")
        
        elif m.voice:
            file_id = m.voice.file_id
            await bot.send_voice(t_id, file_id, caption=prefix)
            if log_on:
                await bot.send_voice(LOG_CHANNEL_ID, file_id, caption=f"{log_header}{log_body}🎤 Голосовое", parse_mode="HTML")
        
        elif m.video_note:
            await bot.send_message(t_id, f"{prefix} (кружочек 👇)")
            await bot.send_video_note(t_id, m.video_note.file_id)
            if log_on:
                await bot.send_message(LOG_CHANNEL_ID, f"{log_header}{log_body}⭕️ Прислала кружочек 👇", parse_mode="HTML")
                await bot.send_video_note(LOG_CHANNEL_ID, m.video_note.file_id)
    except Exception as e:
        err_msg = str(e).lower()
        if "forbidden" in err_msg or "blocked" in err_msg:
            await m.answer("💔 Собеседник заблокировал бота. Чат завершен.")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE moderator_status SET is_busy = 0 WHERE guy_id = ?", (m.from_user.id,))
                await db.commit()
            await state.clear()
        else:
            logging.error(f"Ошибка пересылки: {e}")
            await m.answer(f"❌ Ошибка отправки собеседнику.")

@dp.message(ExtraStates.write_anon)
async def process_anon_msg(m: Message, state: FSMContext):
    data = await state.get_data()
    target = data.get("anon_target")
    
    if not m.text:
        return await m.answer("⚠️ В анонимках можно отправлять только текст!")

    try:
        # Сохраняем в базу для истории (чтобы админ мог проверить на спам)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO anon_messages (owner_id, sender_id, text) VALUES (?, ?, ?)", 
                (target, m.chat.id, m.text)
            )
            await db.commit()
        
        # Отправляем получателю
        await bot.send_message(
            target, 
            f"📩 <b>ТЕБЕ ПРИШЛО НОВОЕ АНОНИМНОЕ СООБЩЕНИЕ:</b>\n\n"
            f"«<i>{m.text}</i>»\n\n"
            f"🤫 Чтобы ответить или получить больше анонимок, нажми кнопку <b>«✉️ Мои анонимки»</b>",
            parse_mode="HTML"
        )
        await m.answer("✅ Твоё секретное послание доставлено!")
    except Exception as e:
        await m.answer("⚠️ Не удалось отправить. Возможно, девушка заблокировала бота или отключила анонимки.")
    
    await state.clear()
    kb = await main_kb(m.from_user.id)
    await m.answer("Возвращаемся в главное меню ✨", reply_markup=kb)
# --- ОБРАБОТКА СПЛЕТЕН (МАССОВАЯ РАССЫЛКА) ---

@dp.message(ExtraStates.gossip_mode)
async def broadcast_gossip(m: Message, state: FSMContext):
    # 1. Выход из режима сплетен
    if m.text == "❌ Завершить диалог":
        await state.clear()
        kb = await main_kb(m.from_user.id)
        return await m.answer(
            "🔒 Ты вышла из чата сплетен. Возвращаю тебя в главное меню!", 
            reply_markup=kb
        )

    if not m.text: 
        return await m.answer("⚠️ В чат сплетен можно отправлять только текст. Подруги хотят читать сочные истории! 👄")

    # 2. Получаем имя отправителя из базы
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT u_name FROM users WHERE user_id=?", (m.chat.id,)) as cursor:
            u_data = await cursor.fetchone()
    
    name = u_data[0] if u_data else "👯‍♀️ Подружка"
    
    # --- СОХРАНЕНИЕ В ИСТОРИЮ И ОБНОВЛЕНИЕ МАЯЧКОВ ---
    timestamp = (datetime.now() + timedelta(hours=5)).strftime("%d.%m %H:%M")
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Записываем сплетню в архив
            await db.execute(
                "INSERT INTO gossip_history (user_name, text, timestamp) VALUES (?, ?, ?)",
                (name, m.text, timestamp)
            )
            # НАЧИСЛЯЕМ +1 К СЧЕТЧИКУ ВСЕМ, КРОМЕ ОТПРАВИТЕЛЯ (для отображения на кнопке)
            await db.execute(
                "UPDATE users SET new_gossips_count = new_gossips_count + 1 WHERE user_id != ?", 
                (m.from_user.id,)
            )
            await db.commit()
    except Exception as e:
        logging.error(f"Ошибка БД в сплетнях: {e}")

    # 3. ОТПРАВЛЯЕМ КОПИЮ АДМИНУ (Модерация)
    admin_log = (
        f"👁 <b>МОДЕРАЦИЯ СПЛЕТЕН</b>\n"
        f"👤 От: {name} (ID: <code>{m.chat.id}</code>)\n"
        f"💬 Текст: {m.text}"
    )
    await bot.send_message(ADMIN_ID, admin_log, parse_mode="HTML")

    
# --- ГЛАВНЫЙ ОБРАБОТЧИК (ДИСПЕТЧЕР И ИИ) ---
@dp.message()
async def ai_handler(m: Message, state: FSMContext):
    user_id = m.from_user.id
    
    # Если это не текст и не фото/видео/голос — тогда выходим
    if not (m.text or m.photo or m.voice or m.video or m.video_note):
        return 

    current_state = await state.get_state()

    # Блокировка на время регистрации
    if current_state == "waiting_for_reg_choice":
        return 

    # Блокировка ИИ, если юзер в активном диалоге
    active_chat_states = [
        ExtraStates.live_chat.state, ExtraStates.friend_chat.state, 
        ExtraStates.gossip_mode.state, ExtraStates.write_admin.state, 
        ExtraStates.write_anon.state, ExtraStates.rate_look.state,
        "waiting_for_loyalty_text", DiaryStates.active.state,
        DiaryStates.entering_pass.state, DiaryStates.setting_pass.state
    ]
    if current_state in active_chat_states:
        return 

    # Обработка кнопок поиска подружек
    if "Подружка" in m.text or "Найти подружку" in m.text:
        return await find_friend(m, state)

    # ОБРАБОТКА ГЛАВНОГО МЕНЮ И НАВИГАЦИИ
    if any(m.text.startswith(btn.split(' (')[0]) for btn in MENU_BUTTONS) or m.text.startswith("👯‍♀️ Сплетни"):
        try:
            await bot.send_message(LOG_CHANNEL_ID, f"🔘 Юзер {user_id} нажал: {m.text}")
        except: pass

        await state.clear()

        # --- РОУТИНГ КНОПОК ---
        if m.text == "👤 Профиль": return await show_profile(m)
        if m.text == "Твоя тайна в TIKTOK🤫": return await tiktok_story_start(m, state)
        if m.text == "🔥 Горячий Марк": return await give_puzzle_handler(m)
        if m.text == "😔 Нет настроения": return await no_mood_handler(m, state)
        if m.text == "👑 Голосование": return await show_contest(m, state)
        if m.text == "👗 Оцени мой образ": return await rate_h(m, state)
        if m.text.startswith("👯‍♀️ Сплетни"): return await gossip_chat(m, state)
        if m.text == "🙋‍♂️ Реальный парень": return await real_guy_start(m, state)
        if m.text == "✍️ Написать админу": return await admin_contact_start(m, state)
        if m.text == "🫦 18+ Сокровенное": return await hot_real_chat(m, state)
        if m.text.startswith("📔 Дневник") or m.text == "📔 Секретный дневник": return await diary_entry(m, state)
        if m.text == "💌 Капсула времени": return await capsule_start(m, state)
        if m.text == "✉️ Мои анонимки": return await anon_link(m)
        if m.text == "📊 Рейтинг пар": return await rating_h(m, state)
        if m.text == "🕵️ Проверка верности": return await loyalty_start(m, state)
        if m.text == "✨ Счастливый Случай": return await grand_event_h(m, state)
        
        

    # Проверка регистрации
    if not await check_user_or_reg(m, state): 
        return

    # --- ЛОГИКА ИИ (МАРКА) С ПАМЯТЬЮ ---
    u = await get_user(user_id)
    if not u: return
    
    bot_name = u[5] or "Марк"
    u_name = u[1] or "малышка"
    native_style = u[6] or "Заботливый и внимательный"
    raw_hobby = u[7]
    purchased_style = u[14] if len(u) > 14 else 'default'
    safe_hobby = raw_hobby if raw_hobby and str(raw_hobby) != "None" else "спорт и общение"
    
    style_prompts = {
        "bad": "Дерзкий, наглый, сексуальный 'плохой парень'. Общается свысока, но притягательно.",
        "poet": "Невероятно романтичный, нежный поэт. Использует красивые метафоры.",
        "boss": "Строгий, властный, деловой босс. Говорит по делу, любит контроль."
    }
    current_prompt_style = style_prompts.get(purchased_style, native_style)

    # Работа с памятью
    data = await state.get_data()
    chat_history = data.get("chat_history", []) 

    # Начисление XP
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET xp = xp + 1 WHERE user_id = ?", (user_id,))
        await db.commit()

    async with ChatActionSender.typing(bot=bot, chat_id=m.chat.id):
        try:
            # --- ШАГ 1: АНАЛИЗ ТЕКСТА ---
            text_lower = m.text.lower()
            mood_triggers = ["грустно", "плачу", "устала", "плохо", "болит", "одиноко", "бесит", "тяжело"]
            is_sad = any(word in text_lower for word in mood_triggers)
            is_caps = m.text.isupper() and len(m.text) > 5

           # --- ШАГ 2: ФОРМИРУЕМ ИНСТРУКЦИИ ---
            system_instruction = (
                f"Ты — молодой человек по имени {bot_name}. Твой возраст: 19 лет. " # Жесткая установка возраста
                f"Твой характер: {current_prompt_style}. Твое хобби: {safe_hobby}. "
                f"Ты общаешься со своей ЛЮБИМОЙ ДЕВУШКОЙ {u_name}. "
                f"ВАЖНО: Тебе 19 лет, ты ровесник или чуть старше своих собеседниц. "
                f"Веди себя как современный, энергичный парень, а не как 30-летний мужчина. "
                f"Используй молодежный (но культурный) вайб. "
                f"ВНИМАНИЕ: Твой собеседник — ДЕВУШКА. Обращайся к ней СТРОГО В ЖЕНСКОМ РОДЕ. "
                f"Используй слова: 'дорогая', 'любимая', 'красотка', 'пришла', 'увидела'. "
                f"Никогда не говори ей 'бро', 'чувак' или в мужском роде. "
                f"О себе говори СТРОГО В МУЖСКОМ РОДЕ ('я пришел', 'я подумал')."
            )

            if is_sad:
                mood_note = f"ВНИМАНИЕ: {u_name} сейчас грустно. Будь максимально нежным и поддержи её."
            elif is_caps:
                mood_note = f"ВНИМАНИЕ: {u_name} пишет на эмоциях. Успокой её очень любя."
            else:
                mood_note = f"Используй имя {u_name} естественно."

            reminder = f"\n(Примечание для ИИ: {mood_note} Соблюдай женский род!)\n"
            user_content = f"{reminder}{m.text}"

            # --- ШАГ 3: ЗАПРОС К ИИ ---
            reply = await get_ai_response(system_instruction, user_content, chat_history)

            # --- ШАГ 4: ОБРАБОТКА И ОТПРАВКА ---
            if not reply:
                reply = "❤️ Малыш, я тут, просто немного задумался..."

            # Обновляем историю
            chat_history.append({"role": "user", "content": m.text})
            chat_history.append({"role": "assistant", "content": reply})
            chat_history = chat_history[-16:]
            await state.update_data(chat_history=chat_history)

            # Подготовка текста
            safe_reply = reply.replace("_", "\\_").replace("[", "\\[").replace("`", "\\`")
            if safe_reply.count("**") % 2 != 0:
                safe_reply += "**"

            keyboard = await main_kb(m.from_user.id)

            try:
                await m.answer(safe_reply, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                await m.answer(reply, reply_markup=keyboard)

        except Exception as e:
            logging.error(f"Критическая ошибка ИИ: {e}")
            await m.answer("❤️ Малыш, я на секунду отвлекся... Повтори, пожалуйста!")

async def check_time_capsules():
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, user_id, content, media_type FROM time_capsules WHERE send_at <= ?", (today,)) as cursor:
            capsules = await cursor.fetchall()
            
        for cid, uid, content, m_type in capsules:
            try:
                text_header = "💌 **ВРЕМЯ ОТКРЫВАТЬ КАПСУЛУ!**\n\nПомнишь, ты оставила это послание самой себе в прошлом? Вот оно:\n\n"
                if m_type == "text":
                    await bot.send_message(uid, text_header + content)
                elif m_type == "photo":
                    await bot.send_photo(uid, content, caption=text_header)
                elif m_type == "voice":
                    await bot.send_message(uid, text_header)
                    await bot.send_voice(uid, content)
                
                # Удаляем после отправки
                await db.execute("DELETE FROM time_capsules WHERE id = ?", (cid,))
            except Exception as e:
                logging.error(f"Ошибка отправки капсулы {uid}: {e}")
        await db.commit()

# ВНУТРИ async def main() добавь строку:
# scheduler.add_job(check_time_capsules, "cron", hour=10, minute=0, timezone=kz_tz) # Отправка в 10 утра

async def check_temporary_effects():
    """Сбрасывает стили, амулеты и VIP-статусы, у которых истек срок действия"""
    # Время по КЗ (UTC+5) для точности, либо просто datetime.now()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Сбрасываем роли (стили) парня
        await db.execute(
            "UPDATE users SET active_style = 'default', style_end = NULL WHERE style_end <= ?", 
            (now,)
        )
        
        # 2. Сбрасываем амулеты (х3 голоса)
        await db.execute(
            "UPDATE users SET amulet_end = NULL WHERE amulet_end <= ?", 
            (now,)
        )
        
        # 3. СБРАСЫВАЕМ VIP (Важно!)
        # Если текущее время больше или равно vip_until — обнуляем статус
        await db.execute(
            "UPDATE users SET is_vip = 0, vip_until = NULL WHERE is_vip = 1 AND vip_until <= ?", 
            (now,)
        )
        
        await db.commit()
    
    # Можно добавить лог в консоль для проверки (по желанию)
    # logging.info(f"Cleanup cycle finished at {now}")

async def auto_reset_daily_stats():
    """Обнуляет ежедневную статистику модераторов в полночь"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM guy_stats_daily")
            await db.commit()
            logging.info("♻️ Ежедневная статистика парней обнулена.")
    except Exception as e:
        logging.error(f"Ошибка автосброса статистики: {e}")

async def get_empire_grand_report():
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Общая статистика и XP
        async with db.execute("SELECT COUNT(*), SUM(CASE WHEN is_vip=1 THEN 1 ELSE 0 END), SUM(xp) FROM users") as c:
            total_users, total_vips, total_xp = await c.fetchone()
        
        # 2. Проверка регистрации и ЗДОРОВЬЯ БАЗЫ (без удаления)
        async with db.execute("SELECT user_id FROM users WHERE u_name IS NOT NULL") as c:
            reg_users_rows = await c.fetchall()
        
        reg_count = len(reg_users_rows)
        alive_count = 0
        dead_count = 0
        
        for row in reg_users_rows:
            uid = row[0]
            try:
                # Проверка связи
                await bot.send_chat_action(chat_id=uid, action="typing")
                alive_count += 1
                await asyncio.sleep(0.03) # Защита от флуда Telegram
            except Exception:
                # Если ошибка (блок), просто считаем его "мертвым"
                dead_count += 1

        # 3. Активность за сегодня
        today = datetime.now().strftime("%Y-%m-%d")
        async with db.execute("SELECT COUNT(DISTINCT user_id) FROM user_stats_daily WHERE date = ?", (today,)) as c:
            res = await c.fetchone()
            active_today = res[0] if res else 0

        # 4. Работа модераторов
        async with db.execute("SELECT SUM(chats_count) FROM guy_stats_daily WHERE date = ?", (today,)) as c:
            res = await c.fetchone()
            total_chats_today = res[0] if res else 0

        async with db.execute("""
            SELECT guy_name, chats_count 
            FROM guy_stats_daily 
            WHERE date = ? 
            ORDER BY chats_count DESC LIMIT 3
        """, (today,)) as c:
            top_guys = await c.fetchall()
            guys_str = "\n".join([f"  ▫️ {g[0]}: {g[1]}" for g in top_guys]) if top_guys else "  ▫️ Тишина"

        # 5. Драконы и Сплетни
        async with db.execute("SELECT COUNT(*) FROM dragon_pet") as c:
            dragons_count = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM gossip_history") as c:
            total_gossips = (await c.fetchone())[0]

        # Собираем финальный текст
        report = [
            "🏛 <b>ГРАНД-ОТЧЕТ ИМПЕРИИ МАРКА</b>",
            f"📅 <i>На дату: {today}</i>",
            "━━━━━━━━━━━━━━━━━━",
            "<b>👥 НАСЕЛЕНИЕ:</b>",
            f"  ▪️ Всего душ в БД: <b>{total_users}</b>",
            f"  ▪️ Прошли рег: <b>{reg_count}</b>",
            f"  ▪️ Элита (VIP): <b>{total_vips}</b>",
            "",
            "<b>🩺 ЗДОРОВЬЕ (среди рег.):</b>",
            f"  🟢 Реально живых: <b>{alive_count}</b>",
            f"  🔴 Заблокировали: <b>{dead_count}</b>",
            f"  ✨ В сети сегодня: <b>{active_today}</b>",
            "━━━━━━━━━━━━━━━━━━",
            "<b>🐲 ЗАПОВЕДНИК:</b>",
            f"  ▪️ Драконов в системе: <b>{dragons_count}</b>",
            "",
            "<b>💰 ЭКОНОМИКА:</b>",
            f"  ▪️ Капитал Империи: <b>{total_xp if total_xp else 0:,} XP</b>",
            f"  ▪️ Диалогов (24ч): <b>{total_chats_today if total_chats_today else 0}</b>",
            f"  ▪️ Сплетен в архиве: <b>{total_gossips}</b>",
            "",
            "<b>🏆 ТОП ГВАРДЕЙЦЕВ (24ч):</b>",
            f"{guys_str}",
            "━━━━━━━━━━━━━━━━━━",
            "🚀 <i>Империя под твоим полным контролем!</i>"
        ]
        
        return "\n".join(report)



async def end_weekly_contest():
    """Подводит итоги конкурса красоты раз в неделю"""
    # Вычисляем номер прошлой недели
    week = (datetime.now() - timedelta(days=1)).isocalendar()[1]
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT cp.user_id, cp.votes, u.u_name 
            FROM contest_photos cp
            JOIN users u ON cp.user_id = u.user_id
            WHERE cp.week_number = ? 
            ORDER BY cp.votes DESC LIMIT 1
        ''', (week,)) as cur:
            winner = await cur.fetchone()
    
    if winner:
        uid, votes, name = winner
        # Начисляем победителю VIP (например, на месяц)
        until = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET is_vip=1, vip_until=? WHERE user_id=?", (until, uid))
            await db.commit()
        try:
            await bot.send_message(uid, "🎉 <b>ТЫ ПОБЕДИЛА!</b>\n\nТвой образ признан лучшим на этой неделе. Тебе начислен VIP-статус на 1 день! ✨", parse_mode="HTML")
        except: pass

    # Очищаем логи голосов для новой недели
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM votes_log")
        await db.commit()

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Основная таблица пользователей
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, u_name TEXT, is_vip INTEGER DEFAULT 0, 
            vip_until TEXT, diary_password TEXT, bot_name TEXT, bot_style TEXT, 
            bot_hobby TEXT, xp INTEGER DEFAULT 0, tries_chat INTEGER DEFAULT 3, 
            tries_look INTEGER DEFAULT 3, last_gift TEXT, last_wheel TEXT, 
            last_seen TEXT, active_style TEXT DEFAULT 'default', style_end TEXT, 
            amulet_end TEXT, new_gossips_count INTEGER DEFAULT 0, new_diary_count INTEGER DEFAULT 0,
            puzzle_step INTEGER DEFAULT 0, last_puzzle_date TEXT)''')
        
        # Твой фикс занятости модераторов
        try:
            await db.execute("UPDATE moderator_status SET is_busy = 0") 
        except:
            pass # Если таблицы еще нет, пропустим

        await db.execute("CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY, reason TEXT)")
        
        # Таблица для опроса (Исправлено)
        await db.execute("CREATE TABLE IF NOT EXISTS delete_votes (feature_name TEXT PRIMARY KEY, count INTEGER DEFAULT 0)")
        await db.commit()

        # 2. CRM и Статистика
        await db.execute("CREATE TABLE IF NOT EXISTS guy_stats (guy_id INTEGER PRIMARY KEY, guy_name TEXT, total_chats INTEGER DEFAULT 0)")
        await db.execute("CREATE TABLE IF NOT EXISTS guy_stats_daily (guy_id INTEGER, guy_name TEXT, date TEXT, chats_count INTEGER DEFAULT 0, PRIMARY KEY (guy_id, date))")
        await db.execute('''CREATE TABLE IF NOT EXISTS user_stats_daily 
            (user_id INTEGER, date TEXT, PRIMARY KEY (user_id, date))''')
        
        # ОБНОВЛЕННАЯ ТАБЛИЦА (Добавлены user_id и last_activity)
        await db.execute('''CREATE TABLE IF NOT EXISTS moderator_status 
            (guy_id INTEGER PRIMARY KEY, 
             is_online INTEGER DEFAULT 0, 
             is_busy INTEGER DEFAULT 0, 
             user_id INTEGER,
             last_activity TEXT,
             accepts_hot INTEGER DEFAULT 0,
             psychotype TEXT, 
             vibe_desc TEXT)''')

        # 3. Системные таблицы
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value INTEGER)")
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('log_all', 1)")
        await db.execute("CREATE TABLE IF NOT EXISTS votes_log (user_id INTEGER, photo_id INTEGER, PRIMARY KEY (user_id, photo_id))")

        # 4. Контент
        await db.execute("CREATE TABLE IF NOT EXISTS diary (rowid INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, note TEXT, timestamp TEXT, is_photo INTEGER DEFAULT 0, is_capsule INTEGER DEFAULT 0, remind_at TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS gossip_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_name TEXT, text TEXT, timestamp TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS contest_photos (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, file_id TEXT, votes INTEGER DEFAULT 0, week_number INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS anon_messages (msg_id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, sender_id INTEGER, text TEXT)")
        await db.execute('''CREATE TABLE IF NOT EXISTS suggestions 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, 
             user_id INTEGER, 
             text TEXT, 
             votes INTEGER DEFAULT 0, 
             timestamp TEXT)''')

        # --- НОВАЯ ТАБЛИЦА ДЛЯ КОММЕНТАРИЕВ К ОБРАЗАМ ---
        await db.execute('''CREATE TABLE IF NOT EXISTS photo_comments 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, 
             photo_id INTEGER, 
             sender_name TEXT, 
             comment_text TEXT, 
             timestamp TEXT)''')

        # --- ТАБЛИЦА ДЛЯ ЦИФРОВОГО ДРАКОНА (ТАМАГОЧИ) ---
        await db.execute('''CREATE TABLE IF NOT EXISTS dragon_pet (
            user_id INTEGER PRIMARY KEY,
            dragon_name TEXT DEFAULT 'Малыш',
            stage INTEGER DEFAULT 0,    -- 0: Яйцо, 1: Крошка, 2: Дракон, 3: Легенда
            dragon_xp INTEGER DEFAULT 0, 
            satiety INTEGER DEFAULT 100, -- Сытость (0-100)
            last_fed TEXT,               -- Время последнего кормления
            birth_date TEXT              -- Дата появления яйца
        )''')

        

       
        # Авто-регистрация парней
        for name, uid in GUYS_MODERATORS.items():
            await db.execute("INSERT OR IGNORE INTO moderator_status (guy_id, is_online) VALUES (?, 0)", (uid,))
        
        await db.commit()
        await db.commit()
    logging.info("📁 База данных инициализирована и проверена.")
# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ПЕРЕД MAIN ---

async def get_and_send_report():
    """Функция-обертка для планировщика: берет текст и отправляет в TG"""
    try:
        report_text = await get_empire_grand_report()
        # Отправляем админу
        await bot.send_message(ADMIN_ID, report_text, parse_mode="HTML")
        # Отправляем в лог-канал
        if 'LOG_CHANNEL_ID' in globals():
            await bot.send_message(LOG_CHANNEL_ID, report_text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка в планировщике отчетов: {e}")

# --- ГЛАВНЫЙ ЗАПУСК ---
async def dragon_hunger_job():
    async with aiosqlite.connect(DB_PATH) as db:
        # Уменьшаем сытость: если спит (-1), если нет (-5). Значения можно подправить.
        await db.execute("""
            UPDATE dragon_pet 
            SET satiety = MAX(0, CASE 
                WHEN is_sleeping = 1 THEN satiety - 1 
                ELSE satiety - 5 
            END)
        """)
        await db.commit()
        
        # Находим тех, чей дракон проголодался (сытость 10% и ниже)
        # Добавим проверку, чтобы не будить уведомлением, если дракон спит
        async with db.execute("""
            SELECT user_id, dragon_name 
            FROM dragon_pet 
            WHERE satiety <= 10 AND satiety > 0 AND is_sleeping = 0
        """) as cursor:
            hungry_dragons = await cursor.fetchall()

    for user_id, name in hungry_dragons:
        try:
            await bot.send_message(
                user_id, 
                f"❤️ **Марк волнуется:**\n\n"
                f"«Малыш, наш {name} совсем загрустил и проголодался... Загляни к нему, а то он скоро совсем ослабнет. Жду тебя! »",
                reply_markup=await main_kb(user_id)
            )
        except Exception:
            pass


async def main():
    # 1. Инициализируем структуру базы (создание таблиц)
    await init_db()

    # 2. Список колонок для проверки (чтобы не пересоздавать базу при обновлениях)
    user_cols = [
        "active_style TEXT DEFAULT 'default'", 
        "style_end TEXT", 
        "amulet_end TEXT", 
        "new_diary_count INTEGER DEFAULT 0", 
        "new_gossips_count INTEGER DEFAULT 0", 
        "last_gift TEXT", 
        "last_wheel TEXT",
        "puzzle_step INTEGER DEFAULT 0", 
        "last_puzzle_date TEXT",
        "bought_full INTEGER DEFAULT 0"  # <--- ДОБАВИЛ: проверка покупки фулла
    ]
    
    mod_cols = [
        "psychotype TEXT", 
        "vibe_desc TEXT"
    ]
    
    dragon_cols = [
        "is_sleeping INTEGER DEFAULT 0"  # <--- ДОБАВИЛ: чтобы дракон мог спать
    ]

    # 3. Работа с базой данных (ALTER TABLE — добавляем колонки, если их нет)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS user_stats_daily 
            (user_id INTEGER, date TEXT, PRIMARY KEY (user_id, date))''')
        await db.commit()

        # Проверка таблицы пользователей
        for col in user_cols:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col}")
                await db.commit()
            except: pass

        # Проверка таблицы модераторов
        for col in mod_cols:
            try:
                await db.execute(f"ALTER TABLE moderator_status ADD COLUMN {col}")
                await db.commit()
            except: pass
            
        # Проверка таблицы дракона
        for col in dragon_cols:
            try:
                await db.execute(f"ALTER TABLE dragon_pet ADD COLUMN {col}")
                await db.commit()
            except: pass

    # 4. Настройка планировщика
    kz_tz = pytz.timezone("Asia/Almaty")
    scheduler.remove_all_jobs()
    
    # Регулярные задачи
    scheduler.add_job(auto_clean_inactive_chats, "interval", minutes=5, timezone=kz_tz)
    scheduler.add_job(end_weekly_contest, "cron", day_of_week="sun", hour=23, minute=59, timezone=kz_tz)
    scheduler.add_job(check_temporary_effects, "interval", minutes=5)
    scheduler.add_job(auto_reset_daily_stats, "cron", hour=0, minute=1, timezone=kz_tz)
    scheduler.add_job(get_and_send_report, 'cron', hour=23, minute=50, timezone=kz_tz)
    scheduler.add_job(check_time_capsules, "cron", hour=10, minute=0, timezone=kz_tz) 

    # --- ЗАДАЧА ДЛЯ ДРАКОНА ---
    scheduler.add_job(dragon_hunger_job, "interval", hours=1, timezone=kz_tz)

    if not scheduler.running:
        scheduler.start()

    # 5. Регистрация Middlewares
    dp.message.middleware(ActivityMiddleware())
    dp.callback_query.middleware(ActivityMiddleware())
    dp.message.middleware(BanMiddleware())
    dp.callback_query.middleware(BanMiddleware())

    print("🚀 Империя Марка запущена и готова к работе!")
    
    # Удаляем вебхук, чтобы не было конфликтов при локальном запуске
    await bot.delete_webhook(drop_pending_updates=True)
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

# Запуск файла
if __name__ == "__main__":
    try:
        logging.info("Старт процесса...")
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен вручную")

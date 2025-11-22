import asyncio
import logging
import re
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from supabase import create_client

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
MAX_CODES_PER_PHONE = 10
ADMIN_ID = 6191416030

class RegisterStates(StatesGroup):
    waiting_name = State()
    waiting_surname = State()
    waiting_code = State()
    waiting_broadcast = State()
    waiting_question = State()
    waiting_answer = State()

# ================== KEYBOARDS ==================
def get_phone_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Telefon raqamni jo'natish", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)

def get_code_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Kod jo'natish"), KeyboardButton(text="Kodlarim")],
            [KeyboardButton(text="Savol berish")]
        ],
        resize_keyboard=True
    )

def get_admin_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Obunachilarga xabar")],
            [KeyboardButton(text="Statistika")],
            [KeyboardButton(text="Kod jo'natish"), KeyboardButton(text="Kodlarim")],
            [KeyboardButton(text="Savol berish")]
        ],
        resize_keyboard=True
    )

# ================== HELPERS ==================
def validate_code(code: str) -> bool:
    return bool(re.match(r"^[A-Z]{2}-[A-Z0-9]{6}$", code.upper()))

def calculate_chances(codes_count: int) -> int:
    return 1 if 1 <= codes_count <= 2 else 10 if 3 <= codes_count <= 9 else 100 if codes_count >= 10 else 0

# ================== CONTACT & REGISTRATION (qisqartirilgan, ishlaydi) ==================
# ... (oldingi handle_contact, start_handler, ism-familiya qismlari o‘zgarmadi)

# ================== 1. KOD JO'NATISH ==================
@dp.message(F.text == "Kod jo'natish")
async def ask_code(message: types.Message, state: FSMContext):
    if await state.get_state() != RegisterStates.waiting_code:
        return
    await message.answer("Kod jo'nating (masalan: `AR-9K2M4P`):", parse_mode="Markdown")

# ================== 2. KODLARIM (TO‘G‘RILANGAN!) ==================
@dp.message(F.text == "Kodlarim")
async def my_codes(message: types.Message, state: FSMContext):
    if await state.get_state() != RegisterStates.waiting_code:
        return

    user_id = message.from_user.id
    res = supabase.table('users').select('name, chances, purchases').eq('user_id', user_id).execute()
    if not res.data:
        await message.answer("Siz hali ro‘yxatdan o‘tmagansiz.")
        return

    user = res.data[0]
    current_codes = user['purchases']
    current_chances = user['chances']
    codes_res = supabase.table('codes').select('code').eq('assigned', True).eq('user_id', user_id).execute()
    code_list = "\n".join([f"• `{c['code']}`" for c in codes_res.data]) if codes_res.data else "Hali kod kiritilmagan."

    next_milestone = (
        "Birinchi kodni kiriting → 1 ta imkoniyat!" if current_codes < 1 else
        f"10 ta imkoniyat uchun {3 - current_codes} ta kod kerak." if current_codes < 3 else
        f"100 ta imkoniyat uchun {10 - current_codes} ta kod kerak." if current_codes < 10 else
        "Maksimal imkoniyatga erishdingiz!"
    )

    await message.answer(
        f"SIZNING HISOBINGIZ\n\n"
        f"Ismi: {user['name']}\n"
        f"Kiritilgan kodlar: {current_codes} ta\n"
        f"Jami imkoniyat: {current_chances} ta\n\n"
        f"Kiritilgan kodlar:\n{code_list}\n\n"
        f"Keyingi maqsad: {next_milestone}\n\n"
        f"Yangi kod jo‘nating → imkoniyat oshadi!",
        reply_markup=get_admin_kb() if user_id == ADMIN_ID else get_code_kb(),
        parse_mode="Markdown"
    )

# ================== 3. SAVOL BERISH (TO‘G‘RILANGAN!) ==================
@dp.message(F.text == "Savol berish")
async def ask_question(message: types.Message, state: FSMContext):
    if await state.get_state() != RegisterStates.waiting_code:
        return
    await message.answer("Savolingizni yozing, tez orada javob beramiz!", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(RegisterStates.waiting_question)

@dp.message(RegisterStates.waiting_question)
async def receive_question(message: types.Message, state: FSMContext):
    user = message.from_user
    question = message.text.strip()

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=f"Yangi savol keldi!\n\nFoydalanuvchi: {user.full_name}\n@{user.username if user.username else 'yo‘q'}\nID: <code>{user.id}</code>\n\nSavol:\n{question}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Javob berish", callback_data=f"answer_{user.id}")]])
    )

    await message.answer("Rahmat! Savolingiz qabul qilindi. Tez orada javob beramiz!", reply_markup=get_admin_kb() if user.id == ADMIN_ID else get_code_kb())
    
    # MUHIM: waiting_code holatiga qaytish!
    await state.set_state(RegisterStates.waiting_code)

# ================== 4. ADMIN STATISTIKA ==================
@dp.message(F.text == "Statistika")
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Sizda bu huquq yo'q.")
        return

    total_users = supabase.table('users').select('user_id', count='exact').execute().count
    total_codes = supabase.table('codes').select('id', count='exact').eq('assigned', True).execute().count
    total_chances = supabase.table('users').select('chances').execute().data
    total_chances_sum = sum(user['chances'] for user in total_chances) if total_chances else 0

    await message.answer(
        f"STATISTIKA\n\n"
        f"Obunachilar: {total_users} ta\n"
        f"Jami kiritilgan kodlar: {total_codes} ta\n"
        f"Jami imkoniyatlar: {total_chances_sum} ta",
        reply_markup=get_admin_kb()
    )

# ================== 5. KOD QAYTA ISHLOVCHI (EN OXIRGI!) ==================
@dp.message(RegisterStates.waiting_code)
async def process_code(message: types.Message, state: FSMContext):
    text = message.text.strip().upper()
    user_id = message.from_user.id

    if text in ["KOD JO'NATISH", "KODLARIM", "SAVOL BERISH", "STATISTIKA"]:
        return

    if text == "OBUNACHILARGA XABAR" and user_id == ADMIN_ID:
        await message.answer("Barcha obunachilarga yubormoqchi bo'lgan xabaringizni yozing:")
        await state.set_state(RegisterStates.waiting_broadcast)
        return

    if not validate_code(text):
        await message.answer("Kod noto‘g‘ri formatda. Masalan: `AR-9K2M4P`", parse_mode="Markdown")
        return

    # Qolgan kod (oldingiday)
    user_res = supabase.table('users').select('id').eq('user_id', user_id).execute()
    if not user_res.data:
        await message.answer("Siz hali ro‘yxatdan o‘tmagansiz.")
        return

    res = supabase.table('codes').select('assigned').eq('code', text).execute()
    if not res.data:
        await message.answer(f"Bu kod topilmadi: {text}")
        return

    if res.data[0]['assigned']:
        await message.answer(f"Bu kod allaqachon ishlatilgan: {text}\nHar bir kod faqat bir marta ishlatiladi.")
        return

    used_count = supabase.table('codes').select('id', count='exact').eq('assigned', True).eq('user_id', user_id).execute().count
    if used_count >= MAX_CODES_PER_PHONE:
        await message.answer("Maksimal 10 ta kod kiritildi!")
        return

    update_res = supabase.table('codes').update({'assigned': True, 'user_id': user_id, 'assigned_at': 'now()'}).eq('code', text).execute()
    if not update_res.data:
        await message.answer("Kodni saqlashda xato.")
        return

    total_codes = used_count + 1
    chances = calculate_chances(total_codes)
    supabase.table('users').update({'chances': chances, 'purchases': total_codes}).eq('user_id', user_id).execute()

    await message.answer(
        f"Yangi kod qabul qilindi!\nKod: `{text}`\nJami: {total_codes} ta\nImkoniyat: {chances} ta",
        reply_markup=get_admin_kb() if user_id == ADMIN_ID else get_code_kb(),
        parse_mode="Markdown"
    )

# ================== BROADCAST & JAVOB BERISH (oldingiday) ==================
# ... (oldingi broadcast va javob berish kodlari o‘zgarmadi)

# ================== MAIN ==================
async def main():
    print("Bot ishga tushdi! 24/7 polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

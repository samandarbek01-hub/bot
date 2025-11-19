import asyncio
import logging
import re
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from supabase import create_client

# ================== ENV ==================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ================== LOGGING ==================
logging.basicConfig(level=logging.INFO)

# ================== BOT ==================
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
MAX_CODES_PER_PHONE = 10

# ================== ADMIN ID ==================
ADMIN_ID = 6191416030

# ================== STATES ==================
class RegisterStates(StatesGroup):
    waiting_name = State()
    waiting_surname = State()
    waiting_code = State()
    waiting_broadcast = State()

# ================== KEYBOARDS ==================
def get_phone_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Telefon raqamni jo'natish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def get_code_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Kod jo'natish"), KeyboardButton(text="Kodlarim")]],
        resize_keyboard=True
    )

def get_admin_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Obunachilarga xabar")],
            [KeyboardButton(text="Kod jo'natish"), KeyboardButton(text="Kodlarim")]
        ],
        resize_keyboard=True
    )

# ================== HELPERS ==================
def validate_code(code: str) -> bool:
    return bool(re.match(r"^[A-Z]{2}-[A-Z0-9]{6}$", code.upper()))

def calculate_chances(codes_count: int) -> int:
    if 1 <= codes_count <= 2:
        return 1
    elif 3 <= codes_count <= 9:
        return 10
    elif codes_count >= 10:
        return 100
    return 0

# ================== CONTACT HANDLER ==================
@dp.message(lambda message: message.contact is not None)
async def handle_contact(message: types.Message, state: FSMContext):
    phone = re.sub(r'\D', '', message.contact.phone_number)
    if not phone.startswith('998') or len(phone) != 12:
        await message.answer(
            "Telefon raqami noto'g'ri formatda!\n"
            "Faqat **tugma orqali** +998XXXXXXXXX formatida jo'nating:",
            reply_markup=get_phone_kb()
        )
        return
    phone = '+' + phone
    user_id = message.from_user.id
    if supabase.table('users').select('id').eq('phone', phone).execute().data:
        await message.answer(
            "Bu telefon raqami allaqachon ro'yxatdan o'tgan.\n"
            "Boshqa raqam kiriting:",
            reply_markup=get_phone_kb()
        )
        return
    await state.update_data(phone=phone)
    await message.answer("Ismingizni kiriting:")
    await state.set_state(RegisterStates.waiting_name)

# ================== MANUAL PHONE REJECTION ==================
@dp.message(lambda message: message.text and re.match(r"^\+998[0-9]{9}$", message.text))
async def reject_manual_phone(message: types.Message):
    current_state = await state.get_state()
    if current_state is None or "waiting_name" not in current_state:
        await message.answer(
            "Telefon raqamini **qo‘lda kiritmang!**\n"
            "Faqat **tugma orqali** jo'nating:",
            reply_markup=get_phone_kb()
        )

# ================== /start ==================
@dp.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text or ""
    deep_link = re.search(r'/start\s+code_([A-Z0-9-]+)', text)
    if deep_link:
        code = deep_link.group(1).upper()
        if validate_code(code):
            await state.update_data(deep_code=code)

    res = supabase.table('users').select('name, chances, phone').eq('user_id', user_id).execute()

    if res.data:
        user = res.data[0]
        data = await state.get_data()
        deep_code = data.get('deep_code')

        if deep_code:
            code_res = supabase.table('codes').select('assigned', 'user_id').eq('code', deep_code).execute()
            if code_res.data and not code_res.data[0]['assigned']:
                used_count = supabase.table('codes').select('id', count='exact').eq('assigned', True).eq('user_id', user_id).execute().count
                if used_count < MAX_CODES_PER_PHONE:
                    update_res = supabase.table('codes').update({
                        'assigned': True,
                        'user_id': user_id,
                        'assigned_at': 'now()'
                    }).eq('code', deep_code).execute()
                    if update_res.data:
                        total_codes = used_count + 1
                        chances = calculate_chances(total_codes)
                        supabase.table('users').update({
                            'chances': chances,
                            'purchases': total_codes
                        }).eq('user_id', user_id).execute()
                        await message.answer(
                            f"**QR-kod orqali kod qabul qilindi!**\n\n"
                            f"Kod: `{deep_code}`\n"
                            f"Jami: **{total_codes} ta**\n"
                            f"Imkoniyat: **{chances} ta**",
                            reply_markup=get_admin_kb() if user_id == ADMIN_ID else get_code_kb()
                        )
                        await state.clear()
                        await state.set_state(RegisterStates.waiting_code)
                        return
                else:
                    await message.answer("**Maksimal 10 ta kod kiritildi!**", reply_markup=get_admin_kb() if user_id == ADMIN_ID else get_code_kb())
            else:
                await message.answer(f"**Bu kod topilmadi yoki allaqachon ishlatilgan: {deep_code}**", reply_markup=get_admin_kb() if user_id == ADMIN_ID else get_code_kb())

        await message.answer(
            f"Salom, **{user['name']}!**\n\n"
            f"Sizda **{user['chances']} ta imkoniyat** bor.\n"
            f"Yangi kod jo'nating yoki kodlaringizni ko'ring:",
            reply_markup=get_admin_kb() if user_id == ADMIN_ID else get_code_kb()
        )
        await state.set_state(RegisterStates.waiting_code)
    else:
        await message.answer(
            "Assalomu alaykum!\n\n"
            "“Hid — bu faqat xotira emas, balki imkon.”\n"
            "Ameer atiri bilan orzularingni ro‘yobga chiqar!\n\n"
            "Har bir xarid — uy yutish imkoniyati!\n\n"
            "Ro‘yxatdan o‘tish uchun telefon raqamingizni tugma orqali jo‘nating.",
            reply_markup=get_phone_kb()
        )

# ================== ISM VA FAMILYA ==================
@dp.message(RegisterStates.waiting_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Familyangizni kiriting:")
    await state.set_state(RegisterStates.waiting_surname)

@dp.message(RegisterStates.waiting_surname)
async def process_surname(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    name = data['name']
    surname = message.text.strip()
    phone = data['phone']
    deep_code = data.get('deep_code')

    insert_res = supabase.table('users').insert({
        'user_id': user_id,
        'name': name,
        'surname': surname,
        'phone': phone,
        'chances': 0,
        'purchases': 0
    }).execute()

    if not insert_res.data:
        await message.answer("Ro'yxatdan o'tishda xato. Qayta urining.")
        return

    if deep_code:
        code_res = supabase.table('codes').select('assigned').eq('code', deep_code).execute()
        if not code_res.data:
            await message.answer(
                f"Ro‘yxatdan o‘tdingiz!\n"
                f"Ismi: {name} {surname}\n"
                f"Telefon: {phone}\n\n"
                f"QR-kod topilmadi: `{deep_code}`\n"
                f"Iltimos, to‘g‘ri QR-kod skanerlang yoki kodni qo‘lda kiriting.",
                reply_markup=get_admin_kb() if user_id == ADMIN_ID else get_code_kb()
            )
        elif code_res.data[0]['assigned']:
            await message.answer(
                f"Ro‘yxatdan o‘tdingiz!\n"
                f"Ismi: {name} {surname}\n"
                f"Telefon: {phone}\n\n"
                f"QR-kod allaqachon band: `{deep_code}`\n"
                f"Har bir kod faqat bir marta ishlatiladi.\n\n"
                f"Yangi kod jo‘nating:",
                reply_markup=get_admin_kb() if user_id == ADMIN_ID else get_code_kb()
            )
        else:
            update_res = supabase.table('codes').update({
                'assigned': True,
                'user_id': user_id,
                'assigned_at': 'now()'
            }).eq('code', deep_code).execute()
            if update_res.data:
                chances = calculate_chances(1)
                supabase.table('users').update({
                    'chances': chances,
                    'purchases': 1
                }).eq('user_id', user_id).execute()
                await message.answer(
                    f"Ro‘yxatdan o‘tdingiz!\n"
                    f"Ismi: {name} {surname}\n"
                    f"Telefon: {phone}\n\n"
                    f"QR-kod orqali kod qo‘shildi!\n"
                    f"Kod: `{deep_code}`\n"
                    f"Imkoniyat: **{chances} ta**",
                    reply_markup=get_admin_kb() if user_id == ADMIN_ID else get_code_kb()
                )
            else:
                await message.answer(
                    f"Ro‘yxatdan o‘tdingiz!\n"
                    f"Ismi: {name} {surname}\n"
                    f"Telefon: {phone}\n\n"
                    f"QR-kod saqlanmadi: `{deep_code}`\n"
                    f"Qayta urining.",
                    reply_markup=get_admin_kb() if user_id == ADMIN_ID else get_code_kb()
                )
    else:
        await message.answer(
            f"Ro‘yxatdan o‘tdingiz!\n"
            f"Ismi: {name} {surname}\n"
            f"Telefon: {phone}\n\n"
            f"Kod jo'natish uchun *Kod jo`natish* tugmasini bosing",
            reply_markup=get_admin_kb() if user_id == ADMIN_ID else get_code_kb()
        )

    await state.clear()
    await state.set_state(RegisterStates.waiting_code)

# ================== KOD JO'NATISH ==================
@dp.message(lambda message: message.text == "Kod jo'natish", RegisterStates.waiting_code)
async def ask_code(message: types.Message):
    await message.answer("Kod jo'nating (masalan: `AR-9K2M4P`):", parse_mode="Markdown")

# ================== KOD QAYTA ISHLOVCHI ==================
@dp.message(RegisterStates.waiting_code)
async def process_code(message: types.Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id

    if code == "KODLARIM":
        await my_codes(message)
        return
    if code == "OBUNACHILARGA XABAR" and user_id == ADMIN_ID:
        await message.answer("Barcha obunachilarga yubormoqchi bo'lgan xabaringizni yozing:")
        await state.set_state(RegisterStates.waiting_broadcast)
        return

    if not validate_code(code):
        await message.answer("Kod noto‘g‘ri formatda. Masalan: `AR-9K2M4P`", parse_mode="Markdown")
        return

    user_res = supabase.table('users').select('id').eq('user_id', user_id).execute()
    if not user_res.data:
        await message.answer("Siz hali ro‘yxatdan o‘tmagansiz. Iltimos, avval telefon raqamingizni jo‘nating.")
        return

    res = supabase.table('codes').select('assigned').eq('code', code).execute()
    if not res.data:
        await message.answer(f"**Bu kod topilmadi: {code}**\nIltimos, to‘g‘ri kod kiriting.")
        return

    if res.data[0]['assigned']:
        await message.answer(
            f"Bu kod allaqachon ishlatilgan: {code}\n"
            "Har bir kod faqat bir marta ishlatiladi.\n\n"
            "Agar bu sizning kodingiz bo‘lsa, murojaat qiling:\n"
            "+998 XX XXX XX XX\n"
            "@support_admin"
        )
        return

    used_count = supabase.table('codes').select('id', count='exact').eq('assigned', True).eq('user_id', user_id).execute().count
    if used_count >= MAX_CODES_PER_PHONE:
        await message.answer("**Maksimal 10 ta kod kiritildi!**\nBoshqa akkaunt orqali davom eting.")
        return

    update_res = supabase.table('codes').update({
        'assigned': True,
        'user_id': user_id,
        'assigned_at': 'now()'
    }).eq('code', code).execute()

    if not update_res.data:
        await message.answer("Kodni saqlashda xato. Qayta urining.")
        return

    t = used_count + 1
    chances = calculate_chances(t)

    supabase.table('users').update({
        'chances': chances,
        'purchases': t
    }).eq('user_id', user_id).execute()

    await message.answer(
        f"**Yangi kod qabul qilindi!**\n"
        f"Kod: `{code}`\n"
        f"Jami kodlar: **{t} ta**\n"
        f"Imkoniyat: **{chances} ta**",
        reply_markup=get_admin_kb() if user_id == ADMIN_ID else get_code_kb(),
        parse_mode="Markdown"
    )

# ================== BROADCAST (ADMIN) ==================
@dp.message(RegisterStates.waiting_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Sizda bu huquq yo'q.")
        return

    broadcast_text = message.text
    users = supabase.table('users').select('user_id').execute().data
    success = 0
    failed = 0
    for user in users:
        try:
            await bot.send_message(chat_id=user['user_id'], text=broadcast_text)
            success += 1
        except:
            failed += 1
        await asyncio.sleep(0.05)

    await message.answer(
        f"Xabar yuborildi!\n"
        f"Muvaffaqiyatli: {success}\n"
        f"Xato: {failed}"
    )
    await state.set_state(RegisterStates.waiting_code)

# ================== KODLARIM

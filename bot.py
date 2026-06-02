import asyncio
import logging
import re
from typing import Dict, Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardRemove

# ==================== Конфигурация ====================
BOT_TOKEN = "8873937657:AAFnkm2zUbnYOUs2x3aX6ce64mrE5ePrMAY"          # Замените на токен вашего бота
BOT_USERNAME = "SvetlogorskQuestBot"              # Имя бота (без @) для генерации QR

# ==================== Данные квеста ====================
# Каждый этап: загадка, правильные ответы (список), сообщение после правильного ответа,
# сообщение после сканирования (опционально)
STAGES = {
    1: {
        "riddle": "Место, где:\nты вроде \"просто зашёл\"\nно вышел с чем-то лишним.\n\nГде ты?",
        "answers": ["березки", "берёзки"],
        "correct_reply": "Верно. (мем)\n\nТеперь иди к этому месту и отсканируй QR-код.",
    },
    2: {
        "riddle": "Там, где деревья, но ты не в лесу.\n\nТут можно:\n— подумать\n— погулять\n— или залезть повыше и пожалеть об этом 😄\n\nКуда тебе?",
        "answers": ["парк", "детская площадка", "веревочный парк", "веревочный", "грин адреналин", "green adrenaline", "green adrenaline sv"],
        "correct_reply": "Куда идти? 👉 ➡️ Верёвочный парк / парк\n\nУра!! Ты нашёл второй ключ! Здесь можно гулять, поболтать, посиять! (мем)\n\nТеперь сканируй QR.",
    },
    3: {
        "riddle": "На улице зелень, на улице лето\nА там только холод, зима и ещё\nТы можешь кататься, и место то, где ты\nНайдёшь новый ключ, но, знай, вход запрещён.",
        "answers": ["ледовый дворец", "ледовый"],
        "correct_reply": "👉 ➡️ Ледовый дворец\n\nЗайти, кстати, возможно очень даже стоит, скоро может быть ближайший сеанс на катке! 😄\n\nТеперь сканируй QR.",
    },
    4: {
        "riddle": "Я открыт только пару дней в неделю,\nВ городе мало мест, где можно торговаться.",
        "answers": ["первомайский рынок", "рынок"],
        "correct_reply": "👉 ➡️ Первомайский рынок\n\nВот это уже другой уровень.\n\nТеперь сканируй QR.",
    },
    5: {
        "riddle": "Там есть танцы, зал, копейка\nСаунд Кафе и батарейки.",
        "answers": ["саунд кафе пассаж", "пассаж"],
        "correct_reply": "👉 ➡️ Пассаж\n\nКрасивый вид на храм, неправда?\n\nТеперь сканируй QR.",
    },
    6: {
        "riddle": "Кому-то в этом году 20, 30, 65.\nУ них в этом году что? (создатель квеста устал его писать)",
        "answers": ["юбилей", "юбилеи"],
        "correct_reply": "👉 ➡️ Юбилейный + Храм\n\nС этой стороны вид ещё красивее! Можно даже сделать селфи)\n\nТеперь сканируй QR.",
    },
    7: {
        "riddle": "По прямой до светофора,\nСлева Брестский магазин\nТы зайди к ним и спроси\nЕсть ли брестские носки\n\nНу что говорят, есть?",
        "answers": ["да", "конечно"],
        "correct_reply": "Я раньше тут постоянно закупалась.\n\nТеперь сканируй QR.",
    },
    8: {
        "riddle": "Два раза туда не войдёшь, оно постоянно меняется.\nА пока туда идёшь, можно преисполниться.\n\nКуда нужно идти?",
        "answers": ["реке", "к реке"],
        "correct_reply": "Верно!\n\nМожешь это сделать сейчас или в пути:\nПрослушай этот монолог\nhttps://youtu.be/_suZGUbIvvM?si=Er091oRBuKQ--adp\n\nЧего ищет идущий к реке?",
    }
}

# Вопрос после монолога (этап 8, часть 2)
MONOLOG_ANSWERS = [
    "покоя", "умиротворения", "гармонии от слияния с бесконечно-вечным",
    "гармонии от слияния с бесконечным вечным", "гармонии",
    "покоя, умиротворения и гармонии от слияния с бесконечно-вечным"
]

FINISH_REPLY = (
    "Для этого нужно соединиться с историей 👉 ➡️ Памятник\n\n"
    "Светлогорск раньше был судостроительным городом! Это памятник…\n"
    "Поздравляю! Ты прошёл квест и проделал длинный путь!\n\n"
    "Теперь отсканируй финальный QR-код у памятника."
)

# Всего точек для сканирования (1..8)
TOTAL_SCAN_POINTS = 8

# ==================== FSM Состояния ====================
class QuestState(StatesGroup):
    answering = State()          # ожидание текстового ответа на загадку
    waiting_scan = State()       # ожидание сканирования QR
    feedback_difficulty = State()  # сбор оценки сложности
    feedback_interest = State()     # сбор оценки интереса
    feedback_address = State()      # сбор адреса пункта выдачи

# ==================== Инициализация бота ====================
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)


# ==================== Вспомогательные функции ====================
def normalize_answer(text: str) -> str:
    """Приводит ответ к нижнему регистру и убирает лишние пробелы/знаки"""
    text = text.lower().strip()
    # удаляем пунктуацию
    text = re.sub(r'[^\w\s]', '', text)
    return text


def check_answer(user_input: str, correct_list: list) -> bool:
    """Проверяет, соответствует ли ответ одному из правильных вариантов"""
    normalized = normalize_answer(user_input)
    for correct in correct_list:
        if normalized == normalize_answer(correct):
            return True
    return False


def make_deep_link(point: int) -> str:
    """Генерирует deep-link для указанной точки"""
    return f"https://t.me/{BOT_USERNAME}?start=point_{point}"


# ==================== Обработчик /start ====================
@dp.message(CommandStart(deep_link=True))
async def handle_deep_link(message: Message, command: CommandStart, state: FSMContext):
    """Обрабатывает переход по QR-коду (start=point_N)"""
    args = command.args
    if not args or not args.startswith("point_"):
        # если параметр не распознан — начинаем квест сначала
        await start_quest(message, state)
        return

    try:
        point_num = int(args.split("_")[1])
    except (IndexError, ValueError):
        await message.answer("❌ Неверный QR-код. Пожалуйста, используйте коды, выданные организаторами.")
        return

    current_state = await state.get_state()
    user_data = await state.get_data()
    expected_point = user_data.get("expected_scan_point")
    current_stage = user_data.get("stage", 1)

    if current_state == QuestState.waiting_scan and expected_point == point_num:
        # Правильное сканирование
        await message.answer("✅ Отлично! Ты подтвердил, что находишься на месте.")
        # Переходим к следующему этапу
        next_stage = current_stage + 1
        if next_stage > TOTAL_SCAN_POINTS:
            # Квест пройден! Переходим к финальной обратной связи
            await finish_quest(message, state, user_data)
        else:
            await state.update_data(stage=next_stage)
            await state.set_state(QuestState.answering)
            await message.answer(f"🔍 Этап {next_stage} из {TOTAL_SCAN_POINTS}\n\n{STAGES[next_stage]['riddle']}")
    else:
        # Неправильное или несвоевременное сканирование
        await message.answer(
            "⚠️ Этот QR-код не подходит сейчас. "
            "Убедись, что ты находишься именно в том месте, которое отгадал, "
            "и что ты уже получил задание идти туда."
        )


@dp.message(CommandStart(deep_link=False))
async def cmd_start_no_deeplink(message: Message, state: FSMContext):
    """Обычная команда /start — начало квеста"""
    await start_quest(message, state)


async def start_quest(message: Message, state: FSMContext):
    """Инициализирует квест с первого этапа"""
    await state.clear()
    await state.update_data(stage=1)
    await state.set_state(QuestState.answering)
    await message.answer(
        "🌟 Добро пожаловать в городской квест!\n\n"
        "Правила:\n"
        "1. Я даю загадку — ты угадываешь место.\n"
        "2. Идёшь туда и сканируешь QR-код.\n"
        "3. После сканирования получаешь следующую загадку.\n\n"
        "Финиш — набережная 🌊\n"
        "В конце тебя ждёт подарок (как минимум брелок 😉).\n\n"
        "Погнали! 🚀"
    )
    await message.answer(f"🔍 Этап 1 из {TOTAL_SCAN_POINTS}\n\n{STAGES[1]['riddle']}")


# ==================== Обработка текстовых ответов ====================
@dp.message(QuestState.answering)
async def handle_answer(message: Message, state: FSMContext):
    """Обрабатывает ответы на загадки"""
    user_data = await state.get_data()
    stage = user_data.get("stage", 1)

    # Особый случай: этап 8 имеет два подвопроса
    if stage == 8:
        # Проверяем, задан ли уже вопрос про монолог
        if "monolog_asked" not in user_data:
            # Первая часть: загадка про реку
            if check_answer(message.text, STAGES[8]["answers"]):
                await state.update_data(monolog_asked=True)
                await message.answer(STAGES[8]["correct_reply"])
            else:
                await message.answer("❌ Неправильно. Попробуй ещё раз.")
            return
        else:
            # Вторая часть: ответ на вопрос про монолог
            if check_answer(message.text, MONOLOG_ANSWERS):
                # Правильный ответ на монолог → переводим в ожидание сканирования финальной точки
                await state.update_data(expected_scan_point=8)
                await state.set_state(QuestState.waiting_scan)
                await message.answer(FINISH_REPLY)
                await message.answer(
                    f"📷 Теперь найди памятник (где соединяется история) и отсканируй QR-код.\n"
                    f"Ссылка для сканирования: {make_deep_link(8)}"
                )
            else:
                await message.answer("❌ Не тот ответ. Послушай монолог внимательнее или подумай о чувствах, которые испытывает идущий к реке.")
            return

    # Для всех остальных этапов (1-7)
    if check_answer(message.text, STAGES[stage]["answers"]):
        # Правильный ответ → переход к ожиданию сканирования
        await state.update_data(expected_scan_point=stage)
        await state.set_state(QuestState.waiting_scan)
        await message.answer(STAGES[stage]["correct_reply"])
        # Подсказываем ссылку для сканирования (можно в виде текста или кнопки)
        await message.answer(
            f"🔗 Теперь отправляйся в это место и отсканируй QR-код.\n"
            f"Ссылка для сканирования: {make_deep_link(stage)}"
        )
    else:
        await message.answer("❌ Неверно. Попробуй ещё раз или подумай над загадкой.")


# ==================== Финиш и сбор обратной связи ====================
async def finish_quest(message: Message, state: FSMContext, user_data: Dict[str, Any]):
    """После сканирования последней точки переходим к опросу"""
    await message.answer(
        "🏆 Поздравляю! Ты успешно прошёл весь квест!\n\n"
        "Осталось совсем немного — ответь на пару вопросов и получи свой подарок."
    )
    await state.set_state(QuestState.feedback_difficulty)
    await message.answer("Насколько сложным был для тебя этот квест? (оценка от 1 до 10)")


@dp.message(QuestState.feedback_difficulty)
async def process_difficulty(message: Message, state: FSMContext):
    try:
        score = int(message.text)
        if 1 <= score <= 10:
            await state.update_data(difficulty=score)
            await state.set_state(QuestState.feedback_interest)
            await message.answer("А насколько интересным? (1 — скучно, 10 — очень увлекательно)")
        else:
            await message.answer("Пожалуйста, введи число от 1 до 10.")
    except ValueError:
        await message.answer("Нужно ввести целое число от 1 до 10.")


@dp.message(QuestState.feedback_interest)
async def process_interest(message: Message, state: FSMContext):
    try:
        score = int(message.text)
        if 1 <= score <= 10:
            await state.update_data(interest=score)
            await state.set_state(QuestState.feedback_address)
            await message.answer(
                "Спасибо за оценку!\n\n"
                "Если хочешь оставить развёрнутый отзыв или предложение к следующему квесту, "
                "заполни Яндекс Форму по ссылке:\nhttps://forms.yandex.ru/... (вставьте вашу ссылку)\n\n"
                "А теперь укажи, пожалуйста, адрес ближайшего пункта выдачи Wildberries или Ozon, "
                "куда мы отправим твой брелок."
            )
        else:
            await message.answer("Введи число от 1 до 10.")
    except ValueError:
        await message.answer("Нужно целое число.")


@dp.message(QuestState.feedback_address)
async def process_address(message: Message, state: FSMContext):
    address = message.text.strip()
    data = await state.get_data()
    # Здесь можно сохранить данные в базу или отправить админу
    logging.info(f"User {message.from_user.id} finished quest. "
                 f"Diff: {data.get('difficulty')}, Int: {data.get('interest')}, "
                 f"Address: {address}")
    await message.answer(
        "🎁 Отлично! Мы отправим подарок по указанному адресу в ближайшее время.\n\n"
        "Целую в плечи! До скорой встречи! 👋"
    )
    await state.clear()


# ==================== Сброс квеста ====================
@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Квест сброшен. Чтобы начать заново, нажми /start.")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🤖 Команды:\n"
        "/start — начать квест (или продолжить с сохранённого прогресса)\n"
        "/cancel — сбросить прогресс и начать заново\n"
        "/help — эта справка\n\n"
        "После угадывания места тебе нужно будет отсканировать QR-код. "
        "QR-коды расположены на соответствующих объектах города."
    )


# ==================== Запуск ====================
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

import logging
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from config import TOKEN, CHANNELS, ADMINS
from db import get_film_title, add_film, is_code_taken, load_films, delete_film
from stats import record_visit, get_stats
import asyncio
import datetime
import signal
import sys

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Флаг для graceful shutdown
is_shutting_down = False

# Обработчик сигналов
def signal_handler(signum, frame):
    global is_shutting_down
    if not is_shutting_down:
        is_shutting_down = True
        logging.info("Received shutdown signal. Starting graceful shutdown...")
        asyncio.create_task(shutdown())

async def shutdown():
    global is_shutting_down
    if is_shutting_down:
        return
    
    is_shutting_down = True
    logging.info("Starting shutdown process...")
    
    try:
        # Останавливаем диспетчер
        await dp.stop_polling()
        
        # Закрываем сессию бота
        await bot.session.close()
        
        logging.info("Bot shutdown complete")
    except Exception as e:
        logging.error(f"Error during shutdown: {e}")
    finally:
        sys.exit(0)

# Регистрируем обработчики сигналов
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Словарь для хранения сообщений
messages_to_delete = {}

# Словарь для хранения состояния добавления фильма
adding_films = {}

# Словарь для отслеживания нажатий на кнопку "Отправил заявку"
submitted_requests = set()

# Функция очистки сообщений
async def delete_messages(chat_id):
    if chat_id in messages_to_delete:
        for msg_id in messages_to_delete[chat_id]:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logging.error(f"Error deleting message {msg_id}: {e}")
        messages_to_delete[chat_id] = []

# Функция автоочистки
async def auto_cleanup():
    while True:
        try:
            for chat_id in list(messages_to_delete.keys()):
                await delete_messages(chat_id)
            await asyncio.sleep(60 * 60)  # 1 час вместо 3 часов
        except Exception as e:
            logging.error(f"Error in auto_cleanup: {e}")
            await asyncio.sleep(60)  # При ошибке подождем минуту и повторим

# Создаем клавиатуру для админов
def get_admin_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Узнать название фильма", callback_data="get_film")],
        [InlineKeyboardButton(text="📋 Список фильмов", callback_data="list_films")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_main")]
    ])
    return keyboard

# Создаем клавиатуру
def get_start_keyboard(user_id):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Узнать название фильма", callback_data="get_film")],
        [InlineKeyboardButton(text="ℹ️ Как пользоваться", callback_data="help")],
        [InlineKeyboardButton(text="📢 Подписаться на каналы", callback_data="subscribe")]
    ])
    
    # Добавляем кнопки для админов
    if user_id in ADMINS:
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="➕ Добавить фильм", callback_data="add_film")])
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="📋 Список фильмов", callback_data="list_films")])
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="🗑 Удалить фильм", callback_data="delete_film")])
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="📊 Статистика", callback_data="stats")])
    
    return keyboard

# Создаем клавиатуру для каналов
def get_channels_keyboard():
    channel_buttons = []
    
    # Название каналов из конфига
    channel_names = ["Вкус Жизни", "Секреты Здоровья", "Тонкости Женского Разума"]
    
    # Создаем кнопки для каждого канала
    for i in range(len(CHANNELS)):
        name = channel_names[i] if i < len(channel_names) else f"Канал {i+1}"
        channel_buttons.append([
            InlineKeyboardButton(text=f"🎯 {name}", url=CHANNELS[i])
        ])
    
    # Добавляем кнопку для подтверждения и возврата
    channel_buttons.append([
        InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")
    ])
    channel_buttons.append([
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=channel_buttons)

# Стартовое сообщение
@dp.message(Command('start'))
async def send_welcome(message: Message):
    try:
        # Записываем посещение
        record_visit(message.from_user.id)
        
        welcome_text = (
            "👋 Привет! Я бот для поиска названий фильмов по коду.\n\n"
            "🎯 Просто отправь мне числовой код фильма, и я расскажу его название.\n"
            "📝 Не забудь подписаться на наши каналы для доступа к информации."
        )
        sent_message = await message.answer(welcome_text, reply_markup=get_start_keyboard(message.from_user.id))
        
        if message.chat.id not in messages_to_delete:
            messages_to_delete[message.chat.id] = []
        messages_to_delete[message.chat.id].extend([message.message_id, sent_message.message_id])
    except Exception as e:
        logging.error(f"Error in send_welcome: {e}")

# Обработка callback-запросов
@dp.callback_query()
async def process_callback(callback: types.CallbackQuery):
    try:
        if callback.data == "get_film":
            sent_message = await callback.message.answer(
                "🔍 Отправь мне числовой код фильма, и я найду его название.",
                reply_markup=get_start_keyboard(callback.from_user.id)
            )
            # Добавляем сообщение в список для удаления
            if callback.message.chat.id not in messages_to_delete:
                messages_to_delete[callback.message.chat.id] = []
            messages_to_delete[callback.message.chat.id].append(sent_message.message_id)
        elif callback.data == "help":
            help_text = (
                "📖 Как пользоваться ботом:\n\n"
                "1️⃣ Отправь мне числовой код фильма\n"
                "2️⃣ Нажми на каждый канал и подай заявку на вступление\n"
                "3️⃣ После подачи заявок нажми кнопку 'Я подписался'\n"
                "4️⃣ Получи название фильма\n\n"
                "❓ Если код не найден, проверь правильность ввода"
            )
            sent_message = await callback.message.answer(help_text, reply_markup=get_start_keyboard(callback.from_user.id))
            # Добавляем сообщение в список для удаления
            if callback.message.chat.id not in messages_to_delete:
                messages_to_delete[callback.message.chat.id] = []
            messages_to_delete[callback.message.chat.id].append(sent_message.message_id)
        elif callback.data == "subscribe":
            subscribe_text = (
                "📢 Для доступа к фильмам необходимо:\n\n"
                "1️⃣ Нажми на каждый канал и подай заявку на вступление\n"
                "2️⃣ После подачи заявок нажми кнопку 'Я подписался'\n"
                "3️⃣ Получи название фильма по коду"
            )
            sent_message = await callback.message.answer(subscribe_text, reply_markup=get_channels_keyboard())
            # Добавляем сообщение в список для удаления
            if callback.message.chat.id not in messages_to_delete:
                messages_to_delete[callback.message.chat.id] = []
            messages_to_delete[callback.message.chat.id].append(sent_message.message_id)
        elif callback.data == "check_subscription":
            user_id = callback.from_user.id
            
            # Добавляем пользователя в список тех, кто нажал "Я подписался"
            submitted_requests.add(user_id)
            
            sent_message = await callback.message.answer(
                "✅ Отлично! Теперь вы можете получить название фильма. Просто отправьте числовой код.",
                reply_markup=get_start_keyboard(callback.from_user.id)
            )
            
            # Добавляем сообщение в список для удаления
            if callback.message.chat.id not in messages_to_delete:
                messages_to_delete[callback.message.chat.id] = []
            messages_to_delete[callback.message.chat.id].append(sent_message.message_id)
        elif callback.data == "back_to_main":
            # Очищаем состояние добавления фильма, если оно было
            if callback.from_user.id in adding_films:
                del adding_films[callback.from_user.id]
                
            welcome_text = (
                "👋 Привет! Я бот для поиска названий фильмов по коду.\n\n"
                "🎯 Просто отправь мне числовой код фильма, и я расскажу его название.\n"
                "📝 Не забудь подать заявки на наши каналы для доступа к информации."
            )
            sent_message = await callback.message.answer(welcome_text, reply_markup=get_start_keyboard(callback.from_user.id))
            # Добавляем сообщение в список для удаления
            if callback.message.chat.id not in messages_to_delete:
                messages_to_delete[callback.message.chat.id] = []
            messages_to_delete[callback.message.chat.id].append(sent_message.message_id)
        elif callback.data == "add_film":
            if callback.from_user.id not in ADMINS:
                await callback.answer("❌ У вас нет прав для добавления фильмов", show_alert=True)
                return
            
            # Добавляем пользователя в процесс добавления фильма
            adding_films[callback.from_user.id] = {"step": "code"}
            
            sent_message = await callback.message.answer(
                "➕ Введите код фильма (только цифры):",
                reply_markup=get_admin_keyboard()
            )
            # Добавляем сообщение в список для удаления
            if callback.message.chat.id not in messages_to_delete:
                messages_to_delete[callback.message.chat.id] = []
            messages_to_delete[callback.message.chat.id].append(sent_message.message_id)
        elif callback.data == "list_films":
            if callback.from_user.id not in ADMINS:
                await callback.answer("❌ У вас нет прав для просмотра списка фильмов", show_alert=True)
                return
            
            films = load_films().get("films", {})
            if not films:
                sent_message = await callback.message.answer(
                    "📋 Список фильмов пуст.",
                    reply_markup=get_start_keyboard(callback.from_user.id)
                )
            else:
                films_list = "📋 Список всех фильмов:\n\n"
                for code, title in sorted(films.items(), key=lambda x: int(x[0])):
                    films_list += f"🎬 Код: {code}\nНазвание: {title}\n\n"
                
                sent_message = await callback.message.answer(
                    films_list,
                    reply_markup=get_start_keyboard(callback.from_user.id)
                )
            
            # Добавляем сообщение в список для удаления
            if callback.message.chat.id not in messages_to_delete:
                messages_to_delete[callback.message.chat.id] = []
            messages_to_delete[callback.message.chat.id].append(sent_message.message_id)
        elif callback.data == "delete_film":
            if callback.from_user.id not in ADMINS:
                await callback.answer("❌ У вас нет прав для удаления фильмов", show_alert=True)
                return
            
            # Добавляем пользователя в процесс удаления фильма
            adding_films[callback.from_user.id] = {"step": "delete_code"}
            
            sent_message = await callback.message.answer(
                "🗑 Введите код фильма для удаления:",
                reply_markup=get_admin_keyboard()
            )
            # Добавляем сообщение в список для удаления
            if callback.message.chat.id not in messages_to_delete:
                messages_to_delete[callback.message.chat.id] = []
            messages_to_delete[callback.message.chat.id].append(sent_message.message_id)
        elif callback.data == "stats":
            if callback.from_user.id not in ADMINS:
                await callback.answer("❌ У вас нет прав для просмотра статистики", show_alert=True)
                return
            
            try:
                # Получаем статистику за разные периоды
                stats_1h = get_stats(1)
                stats_24h = get_stats(24)
                stats_7d = get_stats(24 * 7)
                
                stats_text = (
                    "📊 Статистика бота:\n\n"
                    f"За последний час:\n"
                    f"👥 Уникальных пользователей: {stats_1h.get('unique_users', 0)}\n"
                    f"🔄 Всего посещений: {stats_1h.get('total_visits', 0)}\n\n"
                    f"За последние 24 часа:\n"
                    f"👥 Уникальных пользователей: {stats_24h.get('unique_users', 0)}\n"
                    f"🔄 Всего посещений: {stats_24h.get('total_visits', 0)}\n\n"
                    f"За последнюю неделю:\n"
                    f"👥 Уникальных пользователей: {stats_7d.get('unique_users', 0)}\n"
                    f"🔄 Всего посещений: {stats_7d.get('total_visits', 0)}"
                )
                
                sent_message = await callback.message.answer(
                    stats_text,
                    reply_markup=get_start_keyboard(callback.from_user.id)
                )
                
                if callback.message.chat.id not in messages_to_delete:
                    messages_to_delete[callback.message.chat.id] = []
                messages_to_delete[callback.message.chat.id].append(sent_message.message_id)
            except Exception as e:
                logging.error(f"Error getting stats: {e}")
                await callback.message.answer(
                    "❌ Ошибка при получении статистики",
                    reply_markup=get_start_keyboard(callback.from_user.id)
                )
        
        # Обязательно отвечаем на callback
        await callback.answer()
    except Exception as e:
        logging.error(f"Error in process_callback: {e}")
        try:
            await callback.answer("Произошла ошибка. Попробуйте еще раз.")
        except:
            pass

# Обработка всех остальных сообщений
@dp.message()
async def process_message(message: Message):
    try:
        # Проверяем, находится ли пользователь в процессе добавления фильма
        if message.from_user.id in adding_films:
            if adding_films[message.from_user.id]["step"] == "code":
                if not message.text.isdigit():
                    sent_message = await message.reply(
                        "❌ Код должен быть числом. Попробуйте еще раз:",
                        reply_markup=get_admin_keyboard()
                    )
                else:
                    code = int(message.text)
                    if is_code_taken(code):
                        sent_message = await message.reply(
                            "❌ Этот код уже занят. Пожалуйста, выберите другой код:",
                            reply_markup=get_admin_keyboard()
                        )
                    else:
                        # Сохраняем код и переходим к следующему шагу
                        adding_films[message.from_user.id] = {
                            "step": "title",
                            "code": code
                        }
                        sent_message = await message.reply(
                            "📝 Теперь введите название фильма:",
                            reply_markup=get_admin_keyboard()
                        )
            elif adding_films[message.from_user.id]["step"] == "title":
                # Получаем сохраненный код
                code = adding_films[message.from_user.id]["code"]
                title = message.text.strip()
                
                # Проверяем длину названия
                if len(title) < 2:
                    sent_message = await message.reply(
                        "❌ Название фильма слишком короткое. Введите более длинное название:",
                        reply_markup=get_admin_keyboard()
                    )
                else:
                    # Добавляем фильм
                    add_film(code, title)
                    
                    # Удаляем пользователя из процесса добавления
                    del adding_films[message.from_user.id]
                    
                    sent_message = await message.reply(
                        f"✅ Фильм успешно добавлен!\n\n"
                        f"КОД: {code}\n"
                        f"Название Фильма: {title}",
                        reply_markup=get_start_keyboard(message.from_user.id)
                    )
            elif adding_films[message.from_user.id]["step"] == "delete_code":
                if not message.text.isdigit():
                    sent_message = await message.reply(
                        "❌ Код должен быть числом. Попробуйте еще раз:",
                        reply_markup=get_admin_keyboard()
                    )
                else:
                    code = int(message.text)
                    if not is_code_taken(code):
                        sent_message = await message.reply(
                            "❌ Фильм с таким кодом не найден. Попробуйте другой код:",
                            reply_markup=get_admin_keyboard()
                        )
                    else:
                        # Удаляем фильм
                        film_title = get_film_title(code)
                        delete_film(code)
                        
                        # Удаляем пользователя из процесса удаления
                        del adding_films[message.from_user.id]
                        
                        sent_message = await message.reply(
                            f"✅ Фильм успешно удален!\n\n"
                            f"КОД: {code}\n"
                            f"Название Фильма: {film_title}",
                            reply_markup=get_start_keyboard(message.from_user.id)
                        )
        else:
            # Обрабатываем обычные сообщения
            if message.text and message.text.isdigit():
                user_id = message.from_user.id
                
                if user_id not in submitted_requests:
                    subscribe_text = (
                        "📢 Для доступа к фильмам необходимо:\n\n"
                        "1️⃣ Нажми на каждый канал и подай заявку на вступление\n"
                        "2️⃣ После подачи заявок нажми кнопку 'Я подписался'\n"
                        "3️⃣ Получи название фильма по коду"
                    )
                    sent_message = await message.reply(subscribe_text, reply_markup=get_channels_keyboard())
                    # Добавляем сообщение в список для удаления
                    if message.chat.id not in messages_to_delete:
                        messages_to_delete[message.chat.id] = []
                    messages_to_delete[message.chat.id].extend([message.message_id, sent_message.message_id])
                    return

                film_title = get_film_title(int(message.text))

                if film_title:
                    sent_message = await message.reply(
                        f"🎬 Название фильма: <b>{film_title}</b>",
                        reply_markup=get_start_keyboard(message.from_user.id)
                    )
                else:
                    sent_message = await message.reply(
                        "❌ Фильм с таким кодом не найден. Проверьте правильность кода.",
                        reply_markup=get_start_keyboard(message.from_user.id)
                    )
            else:
                # Если сообщение не числовой код, напоминаем пользователю о формате
                sent_message = await message.reply(
                    "❌ Пожалуйста, отправь корректный числовой код фильма.",
                    reply_markup=get_start_keyboard(message.from_user.id)
                )
        
        # Добавляем сообщение в список для удаления
        if message.chat.id not in messages_to_delete:
            messages_to_delete[message.chat.id] = []
        messages_to_delete[message.chat.id].extend([message.message_id, sent_message.message_id])
    except Exception as e:
        logging.error(f"Error in process_message: {e}")
        try:
            await message.reply("Произошла ошибка. Попробуйте еще раз.", 
                               reply_markup=get_start_keyboard(message.from_user.id))
        except:
            pass

# Запуск бота
async def main():
    try:
        # Запускаем автоочистку в отдельной задаче
        asyncio.create_task(auto_cleanup())
        
        logging.info("Starting bot...")
        
        # Запускаем бота
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Error in main: {e}")
        await shutdown()

if __name__ == '__main__':
    asyncio.run(main())
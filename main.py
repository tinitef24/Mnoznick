import asyncio
import logging
import time
import sqlite3
import warnings
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from contextlib import contextmanager
from collections import Counter
warnings.filterwarnings("ignore", category=DeprecationWarning)

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
import random

BOT_TOKEN = "YOUR-BOT-TOKEN"
ADMIN_ID = 11111111 #Введіть telegram id адміна. Дізнатись - @userinfobot
DB_NAME = "quiz_bot.db"

ANSWER_TIME_LIMITS = {
    1: 15,  
    2: 20,  
    3: 30, 
    'lightning': 5, 
    'sniper': 999,   
    'training': 999  
}

REMINDER_HOURS = [11, 13, 15, 17, 19, 21, 23]

REMINDER_MESSAGES = [
    {
        "emoji": "☀️",
        "greeting": "Привіт",
        "text": "Час для швидкої тренування мозку!\n\n💪 5 хвилин практики = великий прогрес!",
        "cta": "🚀 Розв'яжи 5 прикладів зараз!"
    },
    {
        "emoji": "🎯",
        "greeting": "Гей",
        "text": "Давай перевіримо твою швидкість!\n\n⚡ Спробуй режим Блискавка!",
        "cta": "⚡ Блискавичний раунд!"
    },
    {
        "emoji": "🧠",
        "greeting": "Привітик",
        "text": "Твій мозок готовий до виклику?\n\n🎓 Попрактикуй слабкі місця!",
        "cta": "🎯 Почати тренування!"
    },
    {
        "emoji": "🌟",
        "greeting": "Вітання",
        "text": "Хочеш покращити свій рекорд?\n\n🏆 Подивись на рейтинг!",
        "cta": "📊 До тренування!"
    },
    {
        "emoji": "🔥",
        "greeting": "Йоу",
        "text": "Не втрать свою серію!\n\n💪 Продовжуй практикувати кожен день!",
        "cta": "🎯 Тренуватись!"
    },
    {
        "emoji": "🌙",
        "greeting": "Доброго вечора",
        "text": "Перед сном - швидка розминка?\n\n😴 10 прикладів для гарного сну!",
        "cta": "🌙 Вечірня практика!"
    },
    {
        "emoji": "💡",
        "greeting": "Хей",
        "text": "AI виявив твої слабкі місця!\n\n🤖 Давай їх опрацюємо разом!",
        "cta": "🎓 Навчальний режим!"
    }
]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
class QuizStates(StatesGroup):
    choosing_mode = State()
    choosing_level = State()
    choosing_number = State()
    in_quiz = State()
    waiting_answer = State()
    admin_set_name = State()

@contextmanager
def get_db():
    """Контекстний менеджер для роботи з БД"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def migrate_database():
    """Міграція бази даних для додавання нових колонок"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        try:
            cursor.execute("PRAGMA table_info(answer_history)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'question_type' not in columns:
                logger.info("Додаємо колонку question_type...")
                cursor.execute('ALTER TABLE answer_history ADD COLUMN question_type TEXT DEFAULT "standard"')
            
            if 'mode' not in columns:
                logger.info("Додаємо колонку mode...")
                cursor.execute('ALTER TABLE answer_history ADD COLUMN mode TEXT DEFAULT "normal"')
            
            cursor.execute("PRAGMA table_info(users)")
            user_columns = [row[1] for row in cursor.fetchall()]
            
            if 'custom_name' not in user_columns:
                logger.info("Додаємо колонку custom_name...")
                cursor.execute('ALTER TABLE users ADD COLUMN custom_name TEXT')
            
            if 'reminder_enabled' not in user_columns:
                logger.info("Додаємо колонку reminder_enabled...")
                cursor.execute('ALTER TABLE users ADD COLUMN reminder_enabled BOOLEAN DEFAULT 1')
            
            if 'last_reminder_date' not in user_columns:
                logger.info("Додаємо колонку last_reminder_date...")
                cursor.execute('ALTER TABLE users ADD COLUMN last_reminder_date DATE')
            
            conn.commit()
            logger.info("✅ Міграція завершена")
        except Exception as e:
            logger.error(f"Помилка міграції: {e}")


def init_database():
    """Ініціалізація бази даних"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                custom_name TEXT,
                start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_questions INTEGER DEFAULT 0,
                correct_answers INTEGER DEFAULT 0,
                wrong_answers INTEGER DEFAULT 0,
                best_streak INTEGER DEFAULT 0,
                current_streak INTEGER DEFAULT 0,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reminder_enabled BOOLEAN DEFAULT 1,
                last_reminder_date DATE
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS answer_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                question TEXT,
                question_type TEXT DEFAULT 'standard',
                user_answer INTEGER,
                correct_answer INTEGER,
                is_correct BOOLEAN,
                response_time REAL,
                level INTEGER,
                mode TEXT DEFAULT 'normal',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activity_calendar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                activity_date DATE,
                questions_count INTEGER DEFAULT 0,
                UNIQUE(user_id, activity_date),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weak_spots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                number1 INTEGER,
                number2 INTEGER,
                error_count INTEGER DEFAULT 0,
                last_error TIMESTAMP,
                UNIQUE(user_id, number1, number2),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        conn.commit()
        logger.info("База даних ініціалізована")
    
    migrate_database()


def get_or_create_user(user_id: int, username: str, first_name: str) -> dict:
    """Отримати або створити користувача"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        if user is None:
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name)
                VALUES (?, ?, ?)
            ''', (user_id, username, first_name))
            conn.commit()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = cursor.fetchone()
        
        return dict(user) if user else {}


def update_user_stats(user_id: int, is_correct: bool):
    """Оновити статистику користувача"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        if is_correct:
            cursor.execute('''
                UPDATE users 
                SET total_questions = total_questions + 1,
                    correct_answers = correct_answers + 1,
                    current_streak = current_streak + 1,
                    last_activity = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (user_id,))
            
            cursor.execute('''
                UPDATE users 
                SET best_streak = current_streak
                WHERE user_id = ? AND current_streak > best_streak
            ''', (user_id,))
        else:
            cursor.execute('''
                UPDATE users 
                SET total_questions = total_questions + 1,
                    wrong_answers = wrong_answers + 1,
                    current_streak = 0,
                    last_activity = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (user_id,))
        
        conn.commit()


def save_answer_history(user_id: int, question: str, question_type: str,
                       user_answer: int, correct_answer: int, is_correct: bool, 
                       response_time: float, level: int, mode: str = "normal"):
    """Зберегти історію відповіді"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO answer_history 
            (user_id, question, question_type, user_answer, correct_answer, 
             is_correct, response_time, level, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, question, question_type, user_answer, correct_answer, 
              is_correct, response_time, level, mode))
        conn.commit()


def update_activity_calendar(user_id: int):
    """Оновити календар активності"""
    today = datetime.now().date()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO activity_calendar (user_id, activity_date, questions_count)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, activity_date) 
            DO UPDATE SET questions_count = questions_count + 1
        ''', (user_id, today))
        conn.commit()


def track_weak_spot(user_id: int, num1: int, num2: int):
    """Відстежити слабке місце"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO weak_spots (user_id, number1, number2, error_count, last_error)
            VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, number1, number2) 
            DO UPDATE SET error_count = error_count + 1, last_error = CURRENT_TIMESTAMP
        ''', (user_id, num1, num2))
        conn.commit()


def get_weak_spots(user_id: int, limit: int = 5) -> List[Dict]:
    """Отримати топ слабких місць"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT number1, number2, error_count
            FROM weak_spots
            WHERE user_id = ?
            ORDER BY error_count DESC, last_error DESC
            LIMIT ?
        ''', (user_id, limit))
        return [dict(row) for row in cursor.fetchall()]


def get_activity_calendar(user_id: int, days: int = 30) -> Dict[str, int]:
    """Отримати календар активності"""
    with get_db() as conn:
        cursor = conn.cursor()
        start_date = (datetime.now() - timedelta(days=days)).date()
        cursor.execute('''
            SELECT activity_date, questions_count
            FROM activity_calendar
            WHERE user_id = ? AND activity_date >= ?
            ORDER BY activity_date
        ''', (user_id, start_date))
        return {str(row['activity_date']): row['questions_count'] 
                for row in cursor.fetchall()}


def get_user_stats(user_id: int) -> dict:
    """Отримати статистику користувача"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        return dict(user) if user else {}


def set_custom_name(user_id: int, custom_name: str):
    """Встановити кастомне ім'я користувачу"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET custom_name = ? WHERE user_id = ?', (custom_name, user_id))
        conn.commit()


def get_display_name(user_id: int) -> str:
    """Отримати ім'я для відображення"""
    stats = get_user_stats(user_id)
    return stats.get('custom_name') or stats.get('first_name') or 'User'

class AIAssistant:
    """AI-помічник для аналізу та порад"""
    
    @staticmethod
    def analyze_mistakes(user_id: int) -> str:
        """Аналіз помилок користувача"""
        weak_spots = get_weak_spots(user_id, 5)
        
        if not weak_spots:
            return "🤖 Поки недостатньо даних для аналізу. Продовжуй практикувати!"
        
        analysis = "🤖 AI-АНАЛІЗ ТВОЇХ РЕЗУЛЬТАТІВ\n\n"
        analysis += "📊 Найскладніші приклади:\n"
        
        for i, spot in enumerate(weak_spots, 1):
            num1, num2 = spot['number1'], spot['number2']
            errors = spot['error_count']
            analysis += f"{i}. {num1} × {num2} — помилок: {errors}\n"
        
        analysis += "\n💡 Мої спостереження:\n"
        
        all_numbers = []
        for spot in weak_spots:
            all_numbers.extend([spot['number1'], spot['number2']])
        
        counter = Counter(all_numbers)
        most_common = counter.most_common(3)
        
        if most_common:
            analysis += f"• Найчастіше помиляєшся з числом {most_common[0][0]}\n"
        
        analysis += "\n🎯 Мої рекомендації:\n"
        analysis += "• Попрактикуй ці приклади в режимі Навчання\n"
        analysis += "• Перегляни таблицю множення для складних чисел\n"
        analysis += "• Спробуй розкласти приклади (7×8 = 7×7 + 7)\n"
        
        return analysis
    
    @staticmethod
    def get_motivational_message(accuracy: float, streak: int) -> str:
        """Мотиваційне повідомлення"""
        if accuracy >= 90:
            messages = [
                "🌟 Феноменально! Ти справжній майстер!",
                "🎯 Ідеальна точність! Продовжуй!",
                "🏆 Чудово! Ти легенда!"
            ]
        elif accuracy >= 75:
            messages = [
                "💪 Відмінно! Ще трохи і будеш ідеальним!",
                "👍 Дуже добре! Продовжуй тренуватися!",
                "🎉 Чудовий прогрес!"
            ]
        elif accuracy >= 50:
            messages = [
                "📚 Непогано, але можеш краще!",
                "💡 Практика робить майстра!",
                "🔥 Кожна помилка - це урок!"
            ]
        else:
            messages = [
                "🌱 Початок завжди складний!",
                "💪 Кожен математик починав з помилок!",
                "📖 Переглянь таблиці і спробуй знову!"
            ]
        
        message = random.choice(messages)
        
        if streak >= 10:
            message += f"\n🔥 Неймовірна серія: {streak} підряд!"
        elif streak >= 5:
            message += f"\n✨ Чудова серія: {streak} підряд!"
        
        return message
    
    @staticmethod
    def get_hint(num1: int, num2: int) -> str:
        """Підказка для прикладу"""
        hints = [
            f"💡 Підказка: {num1} × {num2} = {num1} + {num1} + ... ({num2} разів)",
            f"💡 Підказка: {num1} × {num2-1} = {num1 * (num2-1)}, тому {num1} × {num2} = {num1 * (num2-1)} + {num1}",
            f"💡 Підказка: Спробуй розбити на частини!"
        ]
        return random.choice(hints)

def generate_question(level: int, specific_number: Optional[int] = None) -> tuple:
    """Генерує питання залежно від рівня"""
    
    if level == 1:
        if specific_number:
            num1 = specific_number
            num2 = random.randint(2, 9)
        else:
            num1 = random.randint(2, 9)
            num2 = random.randint(2, 9)
    elif level == 2:
        num1 = random.randint(10, 99)
        num2 = random.randint(2, 9)
    else:
        num1 = random.randint(10, 99)
        num2 = random.randint(10, 99)
    
    correct = num1 * num2
    return num1, num2, correct


def get_multiplication_table(number: int) -> str:
    """Генерує таблицю множення для числа"""
    table = f"📋 ТАБЛИЦЯ МНОЖЕННЯ НА {number}\n\n"
    for i in range(1, 11):
        result = number * i
        table += f"{number} × {i:2d} = {result:3d}\n"
    return table


def explain_mistake(user_num1: int, user_num2: int, user_answer: int, correct_answer: int) -> str:
    """Створює детальне пояснення помилки"""
    explanation = f"❌ Неправильно!\n\n"
    explanation += f"📝 Правильна відповідь: {user_num1} × {user_num2} = {correct_answer}\n\n"
    
    if user_answer != 0 and user_answer % user_num1 == 0:
        confused_number = user_answer // user_num1
        if confused_number != user_num2 and 1 <= confused_number <= 10:
            explanation += f"💡 Здається, ти сплутав(ла)!\n"
            explanation += f"{user_num1} × {confused_number} = {user_answer}\n"
            explanation += f"Але нам потрібно: {user_num1} × {user_num2} = {correct_answer}\n\n"
    
    elif user_answer != 0 and user_answer % user_num2 == 0:
        confused_number = user_answer // user_num2
        if confused_number != user_num1 and 1 <= confused_number <= 100:
            explanation += f"💡 Здається, ти сплутав(ла)!\n"
            explanation += f"{confused_number} × {user_num2} = {user_answer}\n"
            explanation += f"Але нам потрібно: {user_num1} × {user_num2} = {correct_answer}\n\n"
    
    explanation += f"💪 Запам'ятай: {user_num1} × {user_num2} = {correct_answer}"
    return explanation

def create_main_menu() -> InlineKeyboardBuilder:
    """Створює головне меню бота"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Почати квіз", callback_data="start_quiz")
    builder.button(text="⚡ Режим Блискавка", callback_data="lightning_mode")
    builder.button(text="🎯 Режим Снайпер", callback_data="sniper_mode")
    builder.button(text="🎓 Режим Навчання", callback_data="training_mode")
    builder.button(text="📋 Таблиця множення", callback_data="view_table")
    builder.button(text="📊 Моя статистика", callback_data="my_stats")
    builder.button(text="📅 Календар активності", callback_data="activity_calendar")
    builder.button(text="🤖 AI-Аналіз", callback_data="ai_analysis")
    builder.button(text="🏆 Рейтинг", callback_data="leaderboard")
    builder.button(text="ℹ️ Інформація", callback_data="info")
    builder.adjust(2, 2, 1, 1, 1, 1, 1, 1)
    return builder


def create_mode_menu() -> InlineKeyboardBuilder:
    """Створює меню вибору режиму"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Випадкові приклади", callback_data="mode_random")
    builder.button(text="🔢 Конкретне число", callback_data="mode_specific")
    builder.button(text="🎯 Тренувати слабкі місця", callback_data="mode_weak_spots")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    return builder


def create_level_menu() -> InlineKeyboardBuilder:
    """Створює меню вибору рівня"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Рівень 1: 2-9 × 2-9", callback_data="level_1")
    builder.button(text="⭐⭐ Рівень 2: 10-99 × 2-9", callback_data="level_2")
    builder.button(text="⭐⭐⭐ Рівень 3: 10-99 × 10-99", callback_data="level_3")
    builder.button(text="🔙 Назад", callback_data="back_mode")
    builder.adjust(1)
    return builder


def create_number_menu() -> InlineKeyboardBuilder:
    """Створює меню вибору конкретного числа"""
    builder = InlineKeyboardBuilder()
    for i in range(2, 10):
        builder.button(text=f"{i}", callback_data=f"number_{i}")
    builder.button(text="🔙 Назад", callback_data="back_mode")
    builder.adjust(4)
    return builder


def create_table_selection_menu() -> InlineKeyboardBuilder:
    """Створює меню вибору числа для перегляду таблиці"""
    builder = InlineKeyboardBuilder()
    for i in range(2, 10):
        builder.button(text=f"Таблиця на {i}", callback_data=f"table_{i}")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(2)
    return builder


def create_after_wrong_answer_menu(num1: int, num2: int) -> InlineKeyboardBuilder:
    """Меню після неправильної відповіді"""
    builder = InlineKeyboardBuilder()
    table_num = num1 if num1 <= 9 else num2 if num2 <= 9 else num1
    builder.button(text=f"📋 Таблиця на {table_num}", callback_data=f"show_table_{table_num}")
    builder.button(text="💡 Підказка", callback_data=f"hint_{num1}_{num2}")
    builder.button(text="▶️ Наступне питання", callback_data="continue_quiz")
    builder.button(text="🏁 Завершити", callback_data="finish_quiz")
    builder.adjust(2, 1, 1)
    return builder

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

active_timers = {}

async def send_daily_reminders():
    """Надсилає нагадування у визначені години"""
    last_reminder_hour = -1
    
    while True:
        try:
            now = datetime.now()
            current_hour = now.hour

            if current_hour in REMINDER_HOURS and current_hour != last_reminder_hour:
                logger.info(f"⏰ Надсилаємо нагадування о {current_hour}:00")
                
                with get_db() as conn:
                    cursor = conn.cursor()
                    today = now.date()
                    
                    cursor.execute('''
                        SELECT user_id, first_name, custom_name, last_activity
                        FROM users
                        WHERE reminder_enabled = 1
                    ''')
                    
                    users = cursor.fetchall()
                    sent_count = 0
                    
                    for user in users:
                        user_id = user['user_id']
                        display_name = user['custom_name'] or user['first_name']
                        
                        try:
                            last_activity = datetime.fromisoformat(user['last_activity'])
                            hours_inactive = (now - last_activity).total_seconds() / 3600
                            
                            if hours_inactive < 3:
                                continue
                        except:
                            pass
                        
                        msg_template = random.choice(REMINDER_MESSAGES)
                        
                        stats = get_user_stats(user_id)
                        total = stats.get('total_questions', 0)
                        streak = stats.get('current_streak', 0)
                        
                        reminder_text = f"{msg_template['emoji']} {msg_template['greeting']}, {display_name}!\n\n"
                        reminder_text += msg_template['text']
                        
                        if total > 0:
                            accuracy = (stats['correct_answers'] / total * 100) if total > 0 else 0
                            reminder_text += f"\n\n📊 Твоя точність: {accuracy:.0f}%"
                        
                        if streak > 0:
                            reminder_text += f"\n🔥 Поточна серія: {streak} підряд!"
                        
                        reminder_text += f"\n\n🎯 {msg_template['cta']}"
                        
                        builder = InlineKeyboardBuilder()
                        
                        start_buttons = [
                            ("🎯 Почати квіз", "start_quiz"),
                            ("⚡ Блискавка", "lightning_mode"),
                            ("🎓 Навчання", "training_mode"),
                            ("🎯 Слабкі місця", "mode_weak_spots")
                        ]
                        
                        main_button = random.choice(start_buttons)
                        builder.button(text=main_button[0], callback_data=main_button[1])
                        builder.button(text="📊 Моя статистика", callback_data="my_stats")
                        builder.button(text="⏰ Відкласти на годину", callback_data="snooze_reminder")
                        builder.button(text="🔕 Вимкнути нагадування", callback_data="disable_reminders")
                        builder.adjust(1, 1, 1, 1)
                        
                        try:
                            await bot.send_message(
                                user_id,
                                reminder_text,
                                reply_markup=builder.as_markup()
                            )
                            sent_count += 1
                            
                            await asyncio.sleep(0.1)
                            
                        except Exception as e:
                            logger.error(f"Помилка нагадування для {user_id}: {e}")
                    
                    logger.info(f"✅ Надіслано {sent_count} нагадувань о {current_hour}:00")
                
                last_reminder_hour = current_hour
                
                await asyncio.sleep(60)
            
            else:
                await asyncio.sleep(60)
                
                if current_hour != last_reminder_hour and current_hour not in REMINDER_HOURS:
                    last_reminder_hour = -1
        
        except Exception as e:
            logger.error(f"Помилка в циклі нагадувань: {e}")
            await asyncio.sleep(60)

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обробник команди /start"""
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"
    first_name = message.from_user.first_name or "User"
    
    user = get_or_create_user(user_id, username, first_name)
    display_name = user.get('custom_name') or first_name
    
    if user['total_questions'] == 0:
        log_msg = f"🆕 Новий користувач!\n👤 ID: {user_id}\n📝 @{username}\n👨‍💼 {first_name}\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        try:
            await bot.send_message(ADMIN_ID, log_msg)
        except:
            pass
    
    await state.clear()
    
    welcome_text = f"""
🎓 Привіт, {display_name}!

Вітаю в боті для вивчення таблиці множення! 📚

🎯 Що я вмію:

📝 Квізи з різними рівнями складності
⚡ Швидкісний режим (5 секунд)
🎯 Снайперський режим (без таймера)
🎓 Навчальний режим (з підказками)
📋 Перегляд таблиць множення
📊 Відстеження твоєї статистики
📅 Календар активності
🤖 AI-аналіз твоїх слабких місць
🏆 Глобальний рейтинг
🔔 Щоденні нагадування

Обирай що тобі подобається! 👇
"""
    
    builder = create_main_menu()
    await message.answer(welcome_text, reply_markup=builder.as_markup())


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Статистика користувача"""
    user_id = message.from_user.id
    stats = get_user_stats(user_id)
    
    if not stats or stats['total_questions'] == 0:
        await message.answer("❌ У тебе ще немає статистики!")
        return
    
    display_name = stats.get('custom_name') or stats['first_name']
    total = stats['total_questions']
    correct = stats['correct_answers']
    accuracy = (correct / total * 100) if total > 0 else 0
    
    stats_text = f"""
📊 СТАТИСТИКА: {display_name}

📅 {stats['start_date'][:10]}
🕐 {stats['last_activity'][:16]}

📈 Показники:
• Питань: {total}
• Правильних: {correct} ✅
• Точність: {accuracy:.1f}%

🔥 Рекорди:
• Найкраща серія: {stats['best_streak']}
• Поточна серія: {stats['current_streak']}

{AIAssistant.get_motivational_message(accuracy, stats['current_streak'])}
"""
    await message.answer(stats_text)


@router.message(Command("setname"))
async def cmd_admin_setname(message: Message, state: FSMContext):
    """Команда адміна - встановити ім'я"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Тільки для адміна!")
        return
    
    await message.answer("👤 Надішли: ID ім'я\n\nПриклад: 12345 Максим")
    await state.set_state(QuizStates.admin_set_name)


@router.message(StateFilter(QuizStates.admin_set_name))
async def process_admin_setname(message: Message, state: FSMContext):
    """Обробка встановлення імені"""
    try:
        parts = message.text.strip().split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("❌ Формат: ID ім'я")
            return
        
        user_id = int(parts[0])
        custom_name = parts[1]
        
        stats = get_user_stats(user_id)
        if not stats:
            await message.answer(f"❌ Користувач {user_id} не знайдений!")
            return
        
        set_custom_name(user_id, custom_name)
        await message.answer(f"✅ Користувачу {user_id} встановлено: {custom_name}")
        
        try:
            await bot.send_message(user_id, f"👤 Адмін встановив тобі ім'я: {custom_name}")
        except:
            pass
        
        await state.clear()
    except ValueError:
        await message.answer("❌ ID має бути числом!")

@router.callback_query(F.data == "start_quiz")
async def start_quiz_callback(callback: CallbackQuery, state: FSMContext):
    """Початок квізу"""
    await callback.answer()
    text = "🎮 ВИБЕРИ РЕЖИМ ГРИ"
    builder = create_mode_menu()
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await state.set_state(QuizStates.choosing_mode)


@router.callback_query(F.data == "lightning_mode")
async def lightning_mode_callback(callback: CallbackQuery, state: FSMContext):
    """Блискавичний режим"""
    await callback.answer()
    await state.update_data(mode="lightning", level=1, question_type="standard")
    text = "⚡ РЕЖИМ БЛИСКАВКА\n\n5 секунд на питання!\nГотовий?"
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Почати!", callback_data="start_lightning")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "sniper_mode")
async def sniper_mode_callback(callback: CallbackQuery, state: FSMContext):
    """Снайперський режим"""
    await callback.answer()
    await state.update_data(mode="sniper", level=1, question_type="standard")
    text = "🎯 РЕЖИМ СНАЙПЕР\n\nБез таймера, але тільки 1 спроба!\nГотовий?"
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Почати!", callback_data="start_sniper")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "training_mode")
async def training_mode_callback(callback: CallbackQuery, state: FSMContext):
    """Навчальний режим"""
    await callback.answer()
    await state.update_data(mode="training", level=1, question_type="standard")
    text = "🎓 РЕЖИМ НАВЧАННЯ\n\nБез таймера + підказки!\nПочнемо?"
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Почати!", callback_data="start_training")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "start_lightning")
async def start_lightning(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await start_quiz_session(callback.message, state)


@router.callback_query(F.data == "start_sniper")
async def start_sniper(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await start_quiz_session(callback.message, state)


@router.callback_query(F.data == "start_training")
async def start_training(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await start_quiz_session(callback.message, state)


@router.callback_query(F.data == "mode_random")
async def mode_random_callback(callback: CallbackQuery, state: FSMContext):
    """Випадкові приклади"""
    await callback.answer()
    await state.update_data(mode="random", specific_number=None, question_type="standard")
    text = "⭐ ВИБЕРИ РІВЕНЬ СКЛАДНОСТІ"
    builder = create_level_menu()
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await state.set_state(QuizStates.choosing_level)


@router.callback_query(F.data == "mode_specific")
async def mode_specific_callback(callback: CallbackQuery, state: FSMContext):
    """Конкретне число"""
    await callback.answer()
    await state.update_data(mode="specific", level=1, question_type="standard")
    text = "🔢 ВИБЕРИ ЧИСЛО (2-9)"
    builder = create_number_menu()
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await state.set_state(QuizStates.choosing_number)


@router.callback_query(F.data == "mode_weak_spots")
async def mode_weak_spots_callback(callback: CallbackQuery, state: FSMContext):
    """Тренування слабких місць"""
    await callback.answer()
    user_id = callback.from_user.id
    weak_spots = get_weak_spots(user_id, 10)
    
    if not weak_spots:
        await callback.message.edit_text("🎯 У тебе немає слабких місць!\n\nПройди кілька квізів.", reply_markup=create_main_menu().as_markup())
        return
    
    examples = [(spot['number1'], spot['number2']) for spot in weak_spots]
    await state.update_data(mode="weak_spots", level=1, question_type="standard", weak_spots_list=examples, weak_spot_index=0)
    
    text = f"🎯 ТРЕНУВАННЯ СЛАБКИХ МІСЦЬ\n\nAI виявив {len(examples)} прикладів.\n\nПочнемо!"
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Почати!", callback_data="start_weak_training")
    builder.button(text="🔙 Назад", callback_data="back_mode")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "start_weak_training")
async def start_weak_training(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await start_quiz_session(callback.message, state)


@router.callback_query(F.data.startswith("level_"))
async def level_callback(callback: CallbackQuery, state: FSMContext):
    """Вибір рівня"""
    await callback.answer()
    level = int(callback.data.split("_")[1])
    await state.update_data(level=level)
    await start_quiz_session(callback.message, state)


@router.callback_query(F.data.startswith("number_"))
async def number_callback(callback: CallbackQuery, state: FSMContext):
    """Вибір числа"""
    await callback.answer()
    number = int(callback.data.split("_")[1])
    await state.update_data(specific_number=number)
    await start_quiz_session(callback.message, state)


@router.callback_query(F.data == "view_table")
async def view_table_callback(callback: CallbackQuery):
    """Переглянути таблицю"""
    await callback.answer()
    text = "📋 ВИБЕРИ ЧИСЛО:"
    builder = create_table_selection_menu()
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("table_"))
async def show_table_callback(callback: CallbackQuery):
    """Показати таблицю"""
    await callback.answer()
    number = int(callback.data.split("_")[1])
    table_text = get_multiplication_table(number)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Інше число", callback_data="view_table")
    builder.button(text="🏠 Головне меню", callback_data="back_main")
    builder.adjust(1)
    await callback.message.edit_text(table_text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("show_table_"))
async def show_table_after_wrong(callback: CallbackQuery):
    """Таблиця після помилки"""
    await callback.answer()
    number = int(callback.data.split("_")[2])
    table_text = get_multiplication_table(number) + "\n\n💡 Вивчи і продовжуй!"
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Продовжити", callback_data="continue_quiz")
    builder.button(text="🏁 Завершити", callback_data="finish_quiz")
    builder.adjust(1)
    await callback.message.edit_text(table_text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("hint_"))
async def show_hint(callback: CallbackQuery):
    """Показати підказку"""
    await callback.answer()
    parts = callback.data.split("_")
    num1, num2 = int(parts[1]), int(parts[2])
    hint = AIAssistant.get_hint(num1, num2)
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Продовжити", callback_data="continue_quiz")
    builder.button(text="🏁 Завершити", callback_data="finish_quiz")
    builder.adjust(1)
    await callback.message.edit_text(hint, reply_markup=builder.as_markup())


@router.callback_query(F.data == "my_stats")
async def show_stats(callback: CallbackQuery):
    """Показати статистику"""
    await callback.answer()
    user_id = callback.from_user.id
    stats = get_user_stats(user_id)
    
    if not stats or stats['total_questions'] == 0:
        await callback.message.edit_text("❌ Немає статистики!", reply_markup=create_main_menu().as_markup())
        return
    
    display_name = stats.get('custom_name') or stats['first_name']
    total = stats['total_questions']
    correct = stats['correct_answers']
    accuracy = (correct / total * 100) if total > 0 else 0
    
    stats_text = f"""
📊 СТАТИСТИКА: {display_name}

📅 {stats['start_date'][:10]} → {stats['last_activity'][:10]}

📈 Показники:
• Питань: {total}
• Правильних: {correct} ✅
• Точність: {accuracy:.1f}%

🔥 Рекорди:
• Найкраща серія: {stats['best_streak']}
• Поточна серія: {stats['current_streak']}

{AIAssistant.get_motivational_message(accuracy, stats['current_streak'])}
"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Головне меню", callback_data="back_main")
    await callback.message.edit_text(stats_text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "ai_analysis")
async def ai_analysis(callback: CallbackQuery):
    """AI-аналіз"""
    await callback.answer()
    user_id = callback.from_user.id
    analysis = AIAssistant.analyze_mistakes(user_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Тренувати слабкі місця", callback_data="mode_weak_spots")
    builder.button(text="🔙 Головне меню", callback_data="back_main")
    builder.adjust(1)
    await callback.message.edit_text(analysis, reply_markup=builder.as_markup())


@router.callback_query(F.data == "activity_calendar")
async def activity_calendar(callback: CallbackQuery):
    """Календар активності"""
    await callback.answer()
    user_id = callback.from_user.id
    calendar_data = get_activity_calendar(user_id, 30)
    
    if not calendar_data:
        text = "📅 КАЛЕНДАР АКТИВНОСТІ\n\nПоки немає даних."
    else:
        text = "📅 КАЛЕНДАР (30 днів)\n\n"
        today = datetime.now().date()
        for i in range(29, -1, -1):
            date = today - timedelta(days=i)
            count = calendar_data.get(str(date), 0)
            emoji = "⬜" if count == 0 else "🟩" if count < 10 else "🟨" if count < 20 else "🟥"
            if i % 7 == 6:
                text += f"\n{date.strftime('%d.%m')} {emoji}"
            else:
                text += f" {emoji}"
        
        total_days = len(calendar_data)
        total_questions = sum(calendar_data.values())
        text += f"\n\n📊 Підсумки:\n• Активних днів: {total_days}\n• Питань: {total_questions}\n\n⬜ 0 | 🟩 1-9 | 🟨 10-19 | 🟥 20+"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Головне меню", callback_data="back_main")
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "leaderboard")
async def leaderboard(callback: CallbackQuery):
    """Рейтинг"""
    await callback.answer()
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT first_name, custom_name, correct_answers, total_questions, best_streak
            FROM users WHERE total_questions > 0
            ORDER BY correct_answers DESC, best_streak DESC LIMIT 10
        ''')
        top_users = cursor.fetchall()
    
    if not top_users:
        text = "🏆 РЕЙТИНГ\n\nПоки порожній."
    else:
        text = "🏆 ТОП-10\n\n"
        for i, user in enumerate(top_users, 1):
            name = user['custom_name'] or user['first_name']
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            acc = (user['correct_answers'] / user['total_questions'] * 100) if user['total_questions'] > 0 else 0
            text += f"{emoji} {name}\n   ✅ {user['correct_answers']} | 🔥 {user['best_streak']} | 📊 {acc:.0f}%\n\n"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Головне меню", callback_data="back_main")
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "info")
async def info(callback: CallbackQuery):
    """Інформація"""
    await callback.answer()
    text = """
ℹ️ ІНФОРМАЦІЯ

📚 Бот для вивчення таблиці множення

🚀 Можливості:
• 3 рівні складності
• 3 спеціальні режими
• AI-помічник
• Календар активності
• Щоденні нагадування
• Аналіз слабких місць
• Глобальний рейтинг

Успіхів! 🚀
"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Головне меню", callback_data="back_main")
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery, state: FSMContext):
    """Назад до головного меню"""
    await callback.answer()
    await state.clear()
    display_name = get_display_name(callback.from_user.id)
    text = f"🎓 Привіт, {display_name}!\n\nОбирай режим:"
    builder = create_main_menu()
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "back_mode")
async def back_mode(callback: CallbackQuery, state: FSMContext):
    """Назад до вибору режиму"""
    await callback.answer()
    text = "🎮 ВИБЕРИ РЕЖИМ"
    builder = create_mode_menu()
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await state.set_state(QuizStates.choosing_mode)


@router.callback_query(F.data == "disable_reminders")
async def disable_reminders(callback: CallbackQuery):
    """Вимкнути нагадування"""
    user_id = callback.from_user.id
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET reminder_enabled = 0 WHERE user_id = ?', (user_id,))
        conn.commit()
    await callback.answer("🔕 Нагадування вимкнено!")
    await callback.message.edit_text("🔕 Нагадування вимкнено.", reply_markup=create_main_menu().as_markup())

@router.callback_query(F.data == "snooze_reminder")
async def snooze_reminder_callback(callback: CallbackQuery):
    """Відкласти нагадування на годину"""
    await callback.answer("⏰ Добре, нагадаю через годину!")
    
    user_id = callback.from_user.id
    display_name = get_display_name(user_id)
    
    async def send_snooze_reminder():
        await asyncio.sleep(3600) 
        
        try:
            text = f"⏰ {display_name}, минула година!\n\n📚 Готовий до тренування?"
            builder = InlineKeyboardBuilder()
            builder.button(text="🚀 Почати!", callback_data="start_quiz")
            builder.button(text="🔕 Вимкнути нагадування", callback_data="disable_reminders")
            builder.adjust(1)
            
            await bot.send_message(user_id, text, reply_markup=builder.as_markup())
        except Exception as e:
            logger.error(f"Помилка відкладеного нагадування: {e}")
    
    asyncio.create_task(send_snooze_reminder())
    
    try:
        await callback.message.delete()
    except:
        pass

async def start_quiz_session(message: Message, state: FSMContext):
    """Початок квізу"""
    data = await state.get_data()
    level = data.get('level', 1)
    specific_number = data.get('specific_number')
    mode = data.get('mode', 'normal')

    if mode == "weak_spots":
        weak_spots_list = data.get('weak_spots_list', [])
        weak_spot_index = data.get('weak_spot_index', 0)
        
        if weak_spot_index >= len(weak_spots_list):
            await message.edit_text("🎉 Всі слабкі місця опрацьовано!", reply_markup=create_main_menu().as_markup())
            await state.clear()
            return
        
        num1, num2 = weak_spots_list[weak_spot_index]
        correct = num1 * num2
        await state.update_data(weak_spot_index=weak_spot_index + 1)
    else:
        num1, num2, correct = generate_question(level, specific_number)
    
    question_start_time = time.time()
    await state.update_data(
        num1=num1,
        num2=num2,
        correct_answer=correct,
        question_count=data.get('question_count', 0) + 1,
        question_start_time=question_start_time
    )
    
    if mode == "lightning":
        time_limit = ANSWER_TIME_LIMITS['lightning']
    elif mode in ["sniper", "training"]:
        time_limit = ANSWER_TIME_LIMITS[mode]
    else:
        time_limit = ANSWER_TIME_LIMITS[level]
    
    question_count = data.get('question_count', 0) + 1
    mode_emoji = {'lightning': '⚡', 'sniper': '🎯', 'training': '🎓', 'weak_spots': '🎯'}.get(mode, '❓')
    
    if mode == "training":
        timer_text = "⏱️ Без таймера!"
    elif mode == "sniper":
        timer_text = "🎯 Без таймера, 1 спроба!"
    else:
        timer_text = f"⏱️ {time_limit} секунд!"
    
    question_text = f"{mode_emoji} ПИТАННЯ #{question_count}\n\n{num1} × {num2} = ?\n\n{timer_text}\n\n💡 Введи відповідь:"
    
    await message.edit_text(question_text)
    await state.set_state(QuizStates.waiting_answer)
    
    if mode not in ["sniper", "training"]:
        timer_id = f"{message.chat.id}_{question_start_time}"
        active_timers[timer_id] = True
        asyncio.create_task(question_timer(message, state, time_limit, timer_id))


async def question_timer(message: Message, state: FSMContext, time_limit: int, timer_id: str):
    """Таймер"""
    await asyncio.sleep(time_limit)
    
    if timer_id not in active_timers:
        return
    
    current_state = await state.get_state()
    if current_state == QuizStates.waiting_answer:
        active_timers.pop(timer_id, None)
        data = await state.get_data()
        user_id = message.chat.id
        
        update_user_stats(user_id, is_correct=False)
        update_activity_calendar(user_id)
        
        num1, num2 = data.get('num1'), data.get('num2')
        correct = data.get('correct_answer')
        question = f"{num1} × {num2}"
        
        save_answer_history(user_id, question, "standard", 0, correct, False, time_limit, data.get('level', 1), data.get('mode', 'normal'))
        
        display_name = get_display_name(user_id)
        log_msg = f"⏰ Таймаут!\n👤 {display_name}\n❓ {question}\n✅ {correct}"
        try:
            await bot.send_message(ADMIN_ID, log_msg)
        except:
            pass
        
        timeout_text = f"⏰ ЧАС ВИЧЕРПАНО!\n\n❌ {question} = ?\n✅ Відповідь: {correct}\n\nБажаєш продовжити?"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="▶️ Продовжити", callback_data="continue_quiz")
        builder.button(text="🏁 Завершити", callback_data="finish_quiz")
        builder.adjust(1)
        
        try:
            await message.edit_text(timeout_text, reply_markup=builder.as_markup())
        except:
            await message.answer(timeout_text, reply_markup=builder.as_markup())
        
        await state.set_state(QuizStates.in_quiz)


@router.message(StateFilter(QuizStates.waiting_answer))
async def process_answer(message: Message, state: FSMContext):
    """Обробка відповіді"""
    user_id = message.from_user.id
    data = await state.get_data()
    
    question_start_time = data.get('question_start_time')
    if question_start_time:
        timer_id = f"{message.chat.id}_{question_start_time}"
        active_timers.pop(timer_id, None)
    
    elapsed_time = time.time() - question_start_time
    mode = data.get('mode', 'normal')
    
    if mode not in ["sniper", "training"]:
        level = data.get('level', 1)
        time_limit = ANSWER_TIME_LIMITS.get('lightning' if mode == 'lightning' else level, 15)
        if elapsed_time > time_limit:
            await message.answer("⏰ Час вже вичерпано!")
            return
    
    try:
        user_answer = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи тільки число!")
        return
    
    num1 = data.get('num1')
    num2 = data.get('num2')
    correct = data.get('correct_answer')
    question_count = data.get('question_count', 1)
    
    update_activity_calendar(user_id)
    
    if user_answer == correct:
        update_user_stats(user_id, is_correct=True)
        save_answer_history(user_id, f"{num1} × {num2}", "standard", user_answer, correct, True, elapsed_time, data.get('level', 1), mode)
        
        stats = get_user_stats(user_id)
        display_name = stats.get('custom_name') or stats.get('first_name')
        
        log_msg = f"✅ Правильно!\n👤 {display_name}\n❓ {num1}×{num2}={correct}\n⏱️ {elapsed_time:.1f}с"
        try:
            await bot.send_message(ADMIN_ID, log_msg)
        except:
            pass
        
        mode_bonus = {'lightning': ' ⚡', 'sniper': ' 🎯', 'training': ' 🎓'}.get(mode, '')
        
        response_text = f"✅ ПРАВИЛЬНО!{mode_bonus}\n\n{num1} × {num2} = {correct}\n\n⏱️ {elapsed_time:.1f}с\n🎯 Питань: {question_count}\n🔥 Серія: {stats['current_streak']}\n\n{AIAssistant.get_motivational_message(stats['correct_answers'] / stats['total_questions'] * 100 if stats['total_questions'] > 0 else 0, stats['current_streak'])}"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="▶️ Наступне", callback_data="continue_quiz")
        builder.button(text="🏁 Завершити", callback_data="finish_quiz")
        builder.adjust(1)
        await message.answer(response_text, reply_markup=builder.as_markup())
        
    else:
        update_user_stats(user_id, is_correct=False)
        save_answer_history(user_id, f"{num1} × {num2}", "standard", user_answer, correct, False, elapsed_time, data.get('level', 1), mode)
        track_weak_spot(user_id, num1, num2)
        
        stats = get_user_stats(user_id)
        display_name = stats.get('custom_name') or stats.get('first_name')
        
        log_msg = f"❌ Помилка\n👤 {display_name}\n❓ {num1}×{num2}\n💬 {user_answer}\n✅ {correct}"
        try:
            await bot.send_message(ADMIN_ID, log_msg)
        except:
            pass
        
        explanation = explain_mistake(num1, num2, user_answer, correct)
        
        if mode == "training":
            explanation += f"\n\n{AIAssistant.get_hint(num1, num2)}"
        
        builder = create_after_wrong_answer_menu(num1, num2)
        await message.answer(explanation, reply_markup=builder.as_markup())
    
    await state.set_state(QuizStates.in_quiz)


@router.callback_query(F.data == "continue_quiz")
async def continue_quiz(callback: CallbackQuery, state: FSMContext):
    """Продовження квізу"""
    await callback.answer()
    await start_quiz_session(callback.message, state)


@router.callback_query(F.data == "finish_quiz")
async def finish_quiz(callback: CallbackQuery, state: FSMContext):
    """Завершення квізу"""
    await callback.answer()
    user_id = callback.from_user.id
    stats = get_user_stats(user_id)
    
    if stats and stats['total_questions'] > 0:
        display_name = stats.get('custom_name') or stats['first_name']
        total = stats['total_questions']
        correct = stats['correct_answers']
        accuracy = (correct / total * 100) if total > 0 else 0
        
        final_text = f"🏁 КВІЗ ЗАВЕРШЕНО!\n\n👤 {display_name}\n\n📊 Статистика:\n• Питань: {total}\n• Правильних: {correct} ✅\n• Точність: {accuracy:.1f}%\n• Найкраща серія: {stats['best_streak']} 🔥\n\n{AIAssistant.get_motivational_message(accuracy, stats['current_streak'])}\n\nДякую за гру! 😊"
    else:
        final_text = "🏁 Квіз завершено!"
    
    builder = create_main_menu()
    await callback.message.edit_text(final_text, reply_markup=builder.as_markup())
    await state.clear()

async def main():
    """Головна функція"""
    init_database()
    dp.include_router(router)
    logger.info("🚀 Бот запущено!")
    
    try:
        await bot.send_message(
            ADMIN_ID, 
            f"🤖 Бот запущено!\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"💾 БД: {DB_NAME}\n"
            f"🔔 Нагадування: {', '.join(map(str, REMINDER_HOURS))} год\n\n" 
            f"✅ AI активний\n"
            f"✅ Календар\n"
            f"✅ Аналіз слабких місць\n"
            f"✅ Спецрежими"
        )
    except Exception as e:
        logger.error(f"Помилка: {e}")

    asyncio.create_task(send_daily_reminders())
    
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⛔ Бот зупинено")


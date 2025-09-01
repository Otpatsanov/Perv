import os
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Конфигурация из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
BASE_URL = 'https://projects.pervye.ru'

class SimpleEventsParser:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        })
    
    def get_all_events(self):
        """Получение всех мероприятий без фильтров"""
        events = []
        
        try:
            print("Загружаю главную страницу...")
            response = self.session.get(BASE_URL, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            print("Страница загружена успешно")
            
            # Ищем все карточки мероприятий
            events = self._parse_events_from_page(soup)
            
        except Exception as e:
            print(f"Ошибка при загрузке страницы: {e}")
            return []
        
        return events
    
    def _parse_events_from_page(self, soup):
        """Парсинг мероприятий с страницы"""
        events = []
        
        # Пробуем разные селекторы для карточек
        selectors = [
            'div.project-card',
            'div.event-card',
            'div.card',
            '.project-item',
            '.event-item',
            'article',
            '[class*="project"]',
            '[class*="event"]',
            '[class*="card"]'
        ]
        
        event_cards = []
        for selector in selectors:
            cards = soup.select(selector)
            if cards:
                event_cards.extend(cards)
                print(f"Найдено {len(cards)} карточек с селектором: {selector}")
                if len(cards) > 0:
                    break  # Берем первый подходящий селектор
        
        if not event_cards:
            # Если не нашли по классам, ищем по тегам
            event_cards = soup.find_all(['article', 'div'])
            print(f"Найдено {len(event_cards)} элементов по тегам")
        
        print(f"Всего карточек для обработки: {len(event_cards)}")
        
        for i, card in enumerate(event_cards[:10]):  # Ограничиваем 10 для теста
            try:
                event_data = self._extract_event_data(card, i)
                if event_data:
                    events.append(event_data)
            except Exception as e:
                print(f"Ошибка при обработке карточки {i}: {e}")
                continue
        
        return events
    
    def _extract_event_data(self, card, index):
        """Извлечение данных из карточки"""
        try:
            # Пробуем найти заголовок
            title_elem = None
            # Ищем заголовки в порядке приоритета
            for tag in ['h1', 'h2', 'h3', 'h4']:
                title_elem = card.find(tag)
                if title_elem:
                    break
            
            if not title_elem:
                # Ищем по классам
                title_selectors = ['title', 'name', 'heading']
                for selector in title_selectors:
                    title_elem = card.find('div', class_=lambda x: x and selector in x.lower() if x else False)
                    if title_elem:
                        break
            
            title = title_elem.get_text(strip=True) if title_elem else f"Мероприятие #{index + 1}"
            
            # Ссылка
            link_elem = card.find('a')
            if link_elem and link_elem.get('href'):
                link = link_elem['href']
                if not link.startswith('http'):
                    if link.startswith('/'):
                        link = BASE_URL + link
                    else:
                        link = f"{BASE_URL}/{link}"
            else:
                link = BASE_URL
            
            # Описание
            desc_elem = None
            # Ищем абзацы
            p_tags = card.find_all('p')
            if p_tags:
                desc_elem = p_tags[0]  # Берем первый абзац
            else:
                # Ищем по классам
                desc_selectors = ['description', 'text', 'content', 'summary']
                for selector in desc_selectors:
                    desc_elem = card.find('div', class_=lambda x: x and selector in x.lower() if x else False)
                    if desc_elem:
                        break
            
            description = desc_elem.get_text(strip=True) if desc_elem else "Описание недоступно"
            
            # Дата
            date_elem = card.find('time') or card.find('div', class_=lambda x: x and 'date' in x.lower() if x else False)
            date_info = date_elem.get_text(strip=True) if date_elem else "Дата не указана"
            
            # Создаем уникальный ID
            event_id = f"event_{index}_{hash(title + link)}"
            
            return {
                'id': event_id,
                'title': title,
                'link': link,
                'description': description[:200] + "..." if len(description) > 200 else description,
                'date': date_info
            }
            
        except Exception as e:
            print(f"Ошибка при извлечении данных из карточки {index}: {e}")
            return None

class TestBot:
    def __init__(self):
        self.parser = SimpleEventsParser()
        self.init_db()
    
    def init_db(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect('events.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS sent_events
                     (event_id TEXT PRIMARY KEY, title TEXT, sent_time TEXT)''')
        conn.commit()
        conn.close()
    
    def is_event_sent(self, event_id):
        """Проверка, было ли мероприятие уже отправлено"""
        conn = sqlite3.connect('events.db')
        c = conn.cursor()
        c.execute("SELECT event_id FROM sent_events WHERE event_id = ?", (event_id,))
        result = c.fetchone()
        conn.close()
        return result is not None
    
    def mark_event_as_sent(self, event_id, title):
        """Отметить мероприятие как отправленное"""
        conn = sqlite3.connect('events.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO sent_events (event_id, title, sent_time) VALUES (?, ?, ?)",
                  (event_id, title, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    def send_events_to_chat(self, context: CallbackContext):
        """Отправка мероприятий в чат"""
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Начинаю проверку мероприятий...")
        
        try:
            events = self.parser.get_all_events()
            print(f"Найдено мероприятий: {len(events)}")
            
            if not events:
                # Отправляем тестовое сообщение
                test_message = "🔍 *Тест парсинга*\n\nПока не найдено мероприятий на сайте."
                context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=test_message,
                    parse_mode='Markdown'
                )
                return
            
            # Отправляем первые 3 мероприятия для теста
            for event in events[:3]:
                if not self.is_event_sent(event['id']):
                    try:
                        message = f"🎯 *Новое мероприятие!*\n\n"
                        message += f"📌 *{event['title']}*\n\n"
                        
                        if event['date'] and event['date'] != "Дата не указана":
                            message += f"📅 {event['date']}\n\n"
                        
                        message += f"📄 {event['description']}\n\n"
                        message += f"🔗 [Подробнее]({event['link']})"
                        
                        # Кнопки
                        keyboard = [[
                            InlineKeyboardButton("🔗 Перейти", url=event['link'])
                        ]]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        context.bot.send_message(
                            chat_id=CHAT_ID,
                            text=message,
                            parse_mode='Markdown',
                            disable_web_page_preview=False,
                            reply_markup=reply_markup
                        )
                        
                        self.mark_event_as_sent(event['id'], event['title'])
                        print(f"✓ Отправлено: {event['title']}")
                        
                        time.sleep(1)  # Задержка между сообщениями
                        
                    except Exception as e:
                        print(f"❌ Ошибка отправки: {e}")
            
            print("Проверка завершена")
            
        except Exception as e:
            error_message = f"❌ *Ошибка бота:*\n\n{str(e)}"
            context.bot.send_message(
                chat_id=CHAT_ID,
                text=error_message,
                parse_mode='Markdown'
            )
            print(f"Критическая ошибка: {e}")
    
    def start_command(self, update: Update, context: CallbackContext):
        """Команда /start"""
        welcome_message = (
            "✅ *Тестовый бот мероприятий запущен!*\n\n"
            "Я проверяю сайт projects.pervye.ru и ищу мероприятия.\n"
            "Это тестовая версия без фильтров.\n\n"
            "Команды:\n"
            "/check - проверить мероприятия сейчас\n"
            "/test - тест соединения с сайтом"
        )
        update.message.reply_text(welcome_message, parse_mode='Markdown')
        self.send_events_to_chat(context)
    
    def check_command(self, update: Update, context: CallbackContext):
        """Команда /check"""
        update.message.reply_text("🔍 Проверяю мероприятия...")
        self.send_events_to_chat(context)
        update.message.reply_text("✅ Проверка завершена!")
    
    def test_command(self, update: Update, context: CallbackContext):
        """Команда /test - тест соединения"""
        try:
            update.message.reply_text("🔍 Тестирую соединение с сайтом...")
            
            response = requests.get(BASE_URL, timeout=10)
            status = "✅ Сайт доступен" if response.status_code == 200 else f"❌ Сайт недоступен: {response.status_code}"
            
            test_message = f"*Тест соединения:*\n\n{status}\nКод ответа: {response.status_code}"
            update.message.reply_text(test_message, parse_mode='Markdown')
            
        except Exception as e:
            error_message = f"❌ *Ошибка соединения:*\n\n{str(e)}"
            update.message.reply_text(error_message, parse_mode='Markdown')

def keep_alive():
    """Функция для поддержания активности (если нужно)"""
    pass

def main():
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ ОШИБКА: Не заданы BOT_TOKEN или CHAT_ID")
        print("Пожалуйста, установите переменные окружения!")
        return
    
    bot = TestBot()
    
    # Создание бота
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Регистрация команд
    dp.add_handler(CommandHandler("start", bot.start_command))
    dp.add_handler(CommandHandler("check", bot.check_command))
    dp.add_handler(CommandHandler("test", bot.test_command))
    
    # Планировщик (проверка каждые 2 часа)
    updater.job_queue.run_repeating(
        bot.send_events_to_chat, 
        interval=7200,  # 2 часа
        first=0
    )
    
    print("🤖 Тестовый бот мероприятий запущен!")
    print(f"📍 Целевой сайт: {BASE_URL}")
    print("⏰ Проверка каждые 2 часа")
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

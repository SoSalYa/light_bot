import discord
from discord.ext import commands, tasks
import asyncio
from playwright.async_api import async_playwright
import os
from datetime import datetime
import io
import asyncpg
from PIL import Image
from aiohttp import web
import random
import json
import base64

# Конфигурация
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))
DATABASE_URL = os.getenv('DATABASE_URL')
PORT = int(os.getenv('PORT', 10000))

# Database pool
db_pool = None

# Создание бота
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

async def init_db_pool():
    """Инициализация connection pool для PostgreSQL"""
    global db_pool
    if not db_pool:
        db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
            command_timeout=60
        )
        print("✓ Database pool создан")

async def close_db_pool():
    """Закрытие connection pool"""
    global db_pool
    if db_pool:
        await db_pool.close()
        print("✓ Database pool закрыт")

# HTTP сервер для Render health checks + VNC interface
async def handle_health(request):
    """Health check endpoint"""
    return web.Response(text="OK", status=200)

async def handle_root(request):
    """Root endpoint - VNC interface"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DTEK Bot Remote Control</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }
            .container {
                max-width: 1400px;
                margin: 0 auto;
            }
            .header {
                text-align: center;
                color: white;
                margin-bottom: 30px;
            }
            .header h1 {
                font-size: 2.5em;
                margin-bottom: 10px;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
            }
            .status {
                display: inline-block;
                padding: 8px 20px;
                background: rgba(255,255,255,0.2);
                border-radius: 20px;
                font-size: 14px;
                backdrop-filter: blur(10px);
            }
            .status.online { background: rgba(76, 175, 80, 0.3); }
            .status.offline { background: rgba(244, 67, 54, 0.3); }
            
            .control-panel {
                background: white;
                border-radius: 15px;
                padding: 20px;
                margin-bottom: 20px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            }
            .control-panel h2 {
                margin-bottom: 15px;
                color: #333;
            }
            .buttons {
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
            }
            button {
                padding: 12px 24px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-size: 14px;
                font-weight: 600;
                transition: all 0.3s;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            }
            button:hover {
                transform: translateY(-2px);
                box-shadow: 0 6px 12px rgba(0,0,0,0.15);
            }
            button:active {
                transform: translateY(0);
            }
            .btn-primary {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .btn-success {
                background: linear-gradient(135deg, #56ab2f 0%, #a8e063 100%);
                color: white;
            }
            .btn-danger {
                background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%);
                color: white;
            }
            .btn-info {
                background: linear-gradient(135deg, #3a7bd5 0%, #00d2ff 100%);
                color: white;
            }
            
            .viewer {
                background: white;
                border-radius: 15px;
                padding: 20px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                position: relative;
            }
            .viewer h2 {
                margin-bottom: 15px;
                color: #333;
            }
            .screenshot-container {
                position: relative;
                width: 100%;
                background: #f0f0f0;
                border-radius: 10px;
                overflow: hidden;
                min-height: 600px;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            #screenshot {
                width: 100%;
                height: auto;
                display: block;
                cursor: crosshair;
            }
            .loading {
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                text-align: center;
                color: #999;
            }
            .spinner {
                border: 4px solid #f3f3f3;
                border-top: 4px solid #667eea;
                border-radius: 50%;
                width: 50px;
                height: 50px;
                animation: spin 1s linear infinite;
                margin: 0 auto 10px;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            
            .coordinates {
                position: absolute;
                bottom: 10px;
                left: 10px;
                background: rgba(0,0,0,0.7);
                color: white;
                padding: 8px 12px;
                border-radius: 5px;
                font-family: monospace;
                font-size: 12px;
            }
            
            .info-panel {
                background: white;
                border-radius: 15px;
                padding: 20px;
                margin-top: 20px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            }
            .info-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 15px;
            }
            .info-card {
                background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                padding: 15px;
                border-radius: 10px;
            }
            .info-card h3 {
                font-size: 14px;
                color: #666;
                margin-bottom: 5px;
            }
            .info-card p {
                font-size: 18px;
                font-weight: bold;
                color: #333;
            }
            
            .instructions {
                background: rgba(255, 255, 255, 0.95);
                padding: 20px;
                border-radius: 10px;
                margin-bottom: 20px;
                border-left: 4px solid #667eea;
            }
            .instructions h3 {
                color: #667eea;
                margin-bottom: 10px;
            }
            .instructions ul {
                margin-left: 20px;
                line-height: 1.8;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 DTEK Bot Remote Control</h1>
                <span class="status" id="status">⚪ Connecting...</span>
            </div>
            
            <div class="instructions">
                <h3>📖 Как использовать:</h3>
                <ul>
                    <li><strong>Кликайте по скриншоту</strong> - клики передаются в браузер бота</li>
                    <li><strong>Обновить скриншот</strong> - получить актуальное изображение</li>
                    <li><strong>Пройти капчу</strong> - кликайте по элементам капчи прямо на скриншоте</li>
                    <li>Скриншоты обновляются автоматически каждые 3 секунды</li>
                </ul>
            </div>
            
            <div class="control-panel">
                <h2>🎮 Панель управления</h2>
                <div class="buttons">
                    <button class="btn-primary" onclick="refreshScreenshot()">🔄 Обновить скриншот</button>
                    <button class="btn-success" onclick="initBrowser()">🚀 Инициализировать браузер</button>
                    <button class="btn-info" onclick="manualCheck()">✅ Сделать проверку</button>
                    <button class="btn-danger" onclick="clearCookies()">🍪 Очистить куки</button>
                </div>
            </div>
            
            <div class="viewer">
                <h2>👁️ Удаленный просмотр браузера</h2>
                <div class="screenshot-container">
                    <div class="loading" id="loading">
                        <div class="spinner"></div>
                        <p>Загрузка...</p>
                    </div>
                    <img id="screenshot" style="display: none;" onclick="handleClick(event)">
                    <div class="coordinates" id="coords">X: 0, Y: 0</div>
                </div>
            </div>
            
            <div class="info-panel">
                <h2>📊 Статус бота</h2>
                <div class="info-grid">
                    <div class="info-card">
                        <h3>Браузер</h3>
                        <p id="browser-status">-</p>
                    </div>
                    <div class="info-card">
                        <h3>Последняя дата</h3>
                        <p id="last-update">-</p>
                    </div>
                    <div class="info-card">
                        <h3>Куки</h3>
                        <p id="cookies-status">-</p>
                    </div>
                    <div class="info-card">
                        <h3>Последнее обновление</h3>
                        <p id="last-refresh">-</p>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            let autoRefresh = null;
            let imageNaturalWidth = 0;
            let imageNaturalHeight = 0;
            
            async function request(endpoint, method = 'GET', body = null) {
                const options = { method };
                if (body) {
                    options.headers = { 'Content-Type': 'application/json' };
                    options.body = JSON.stringify(body);
                }
                const response = await fetch(endpoint, options);
                return await response.json();
            }
            
            async function refreshScreenshot() {
                try {
                    const data = await request('/api/screenshot');
                    if (data.screenshot) {
                        const img = document.getElementById('screenshot');
                        img.src = 'data:image/png;base64,' + data.screenshot;
                        img.style.display = 'block';
                        document.getElementById('loading').style.display = 'none';
                        
                        img.onload = function() {
                            imageNaturalWidth = img.naturalWidth;
                            imageNaturalHeight = img.naturalHeight;
                        };
                        
                        document.getElementById('last-refresh').textContent = new Date().toLocaleTimeString();
                    }
                } catch (e) {
                    console.error('Error refreshing screenshot:', e);
                }
            }
            
            async function initBrowser() {
                document.getElementById('status').textContent = '⏳ Инициализация...';
                try {
                    const data = await request('/api/init');
                    alert(data.message);
                    await updateStatus();
                    await refreshScreenshot();
                } catch (e) {
                    alert('Ошибка: ' + e.message);
                }
            }
            
            async function manualCheck() {
                document.getElementById('status').textContent = '⏳ Проверка...';
                try {
                    const data = await request('/api/check');
                    alert(data.message);
                    await refreshScreenshot();
                } catch (e) {
                    alert('Ошибка: ' + e.message);
                }
            }
            
            async function clearCookies() {
                try {
                    const data = await request('/api/clear-cookies', 'POST');
                    alert(data.message);
                    await updateStatus();
                } catch (e) {
                    alert('Ошибка: ' + e.message);
                }
            }
            
            async function handleClick(event) {
                const img = event.target;
                const rect = img.getBoundingClientRect();
                
                const scaleX = imageNaturalWidth / rect.width;
                const scaleY = imageNaturalHeight / rect.height;
                
                const x = Math.round((event.clientX - rect.left) * scaleX);
                const y = Math.round((event.clientY - rect.top) * scaleY);
                
                console.log(`Click: ${x}, ${y}`);
                
                try {
                    const data = await request('/api/click', 'POST', { x, y });
                    console.log(data.message);
                    setTimeout(refreshScreenshot, 1000);
                } catch (e) {
                    console.error('Click error:', e);
                }
            }
            
            document.getElementById('screenshot').addEventListener('mousemove', (e) => {
                const img = e.target;
                const rect = img.getBoundingClientRect();
                const scaleX = imageNaturalWidth / rect.width;
                const scaleY = imageNaturalHeight / rect.height;
                const x = Math.round((e.clientX - rect.left) * scaleX);
                const y = Math.round((e.clientY - rect.top) * scaleY);
                document.getElementById('coords').textContent = `X: ${x}, Y: ${y}`;
            });
            
            async function updateStatus() {
                try {
                    const data = await request('/api/status');
                    
                    document.getElementById('browser-status').textContent = data.browser;
                    document.getElementById('last-update').textContent = data.last_update || '-';
                    document.getElementById('cookies-status').textContent = data.cookies;
                    
                    const statusElem = document.getElementById('status');
                    if (data.browser === '✅ Открыт') {
                        statusElem.className = 'status online';
                        statusElem.textContent = '🟢 Online';
                    } else {
                        statusElem.className = 'status offline';
                        statusElem.textContent = '🔴 Offline';
                    }
                } catch (e) {
                    console.error('Status update error:', e);
                }
            }
            
            function startAutoRefresh() {
                autoRefresh = setInterval(() => {
                    refreshScreenshot();
                    updateStatus();
                }, 3000);
            }
            
            window.onload = async () => {
                await updateStatus();
                await refreshScreenshot();
                startAutoRefresh();
            };
        </script>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def handle_screenshot(request):
    """API: Получить скриншот браузера"""
    try:
        if not checker.page:
            return web.json_response({'error': 'Browser not initialized'}, status=400)
        
        screenshot = await checker.page.screenshot(type='png', full_page=True)
        screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
        
        return web.json_response({
            'screenshot': screenshot_base64,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def handle_click(request):
    """API: Передать клик в браузер"""
    try:
        if not checker.page:
            return web.json_response({'error': 'Browser not initialized'}, status=400)
        
        data = await request.json()
        x = data.get('x', 0)
        y = data.get('y', 0)
        
        await checker.page.mouse.click(x, y)
        print(f"Remote click: ({x}, {y})")
        
        return web.json_response({
            'message': f'Clicked at ({x}, {y})',
            'success': True
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def handle_init(request):
    """API: Инициализировать браузер"""
    try:
        await checker.init_browser()
        return web.json_response({
            'message': 'Браузер инициализирован успешно!',
            'success': True
        })
    except Exception as e:
        return web.json_response({
            'message': f'Ошибка инициализации: {str(e)}',
            'success': False
        }, status=500)

async def handle_check(request):
    """API: Выполнить проверку"""
    try:
        result = await checker.make_screenshots()
        return web.json_response({
            'message': 'Проверка выполнена успешно!',
            'success': True,
            'update_date': result.get('update_date')
        })
    except Exception as e:
        return web.json_response({
            'message': f'Ошибка проверки: {str(e)}',
            'success': False
        }, status=500)

async def handle_clear_cookies(request):
    """API: Очистить куки"""
    try:
        if os.path.exists(checker.cookies_file):
            os.remove(checker.cookies_file)
        return web.json_response({
            'message': 'Куки успешно удалены',
            'success': True
        })
    except Exception as e:
        return web.json_response({
            'message': f'Ошибка: {str(e)}',
            'success': False
        }, status=500)

async def handle_status(request):
    """API: Получить статус бота"""
    browser_status = "✅ Открыт" if checker.browser else "❌ Закрыт"
    cookies_status = "✅ Есть" if os.path.exists(checker.cookies_file) else "❌ Нет"
    
    return web.json_response({
        'browser': browser_status,
        'last_update': checker.last_update_date,
        'cookies': cookies_status
    })

async def start_web_server():
    """Запуск веб-сервера с VNC интерфейсом"""
    app = web.Application()
    
    app.router.add_get('/', handle_root)
    app.router.add_get('/health', handle_health)
    
    app.router.add_get('/api/screenshot', handle_screenshot)
    app.router.add_post('/api/click', handle_click)
    app.router.add_get('/api/init', handle_init)
    app.router.add_get('/api/check', handle_check)
    app.router.add_post('/api/clear-cookies', handle_clear_cookies)
    app.router.add_get('/api/status', handle_status)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"✓ Web server started on port {PORT}")

class DTEKChecker:
    def __init__(self):
        self.browser = None
        self.context = None
        self.playwright = None
        self.page = None
        self.last_update_date = None
        self.cookies_file = 'dtek_cookies.json'
    
    def _get_random_user_agent(self):
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        ]
        return random.choice(user_agents)
    
    async def _save_cookies(self):
        try:
            if self.context:
                cookies = await self.context.cookies()
                with open(self.cookies_file, 'w') as f:
                    json.dump(cookies, f)
                print("✓ Куки сохранены")
        except Exception as e:
            print(f"⚠ Не удалось сохранить куки: {e}")
    
    async def _load_cookies(self):
        try:
            if os.path.exists(self.cookies_file):
                with open(self.cookies_file, 'r') as f:
                    cookies = json.load(f)
                await self.context.add_cookies(cookies)
                print("✓ Куки загружены")
                return True
        except Exception as e:
            print(f"⚠ Не удалось загрузить куки: {e}")
        return False
    
    async def _random_delay(self, min_ms=100, max_ms=500):
        await asyncio.sleep(random.uniform(min_ms/1000, max_ms/1000))
    
    async def _human_move_and_click(self, locator):
        try:
            box = await locator.bounding_box()
            if box:
                x = box['x'] + random.uniform(box['width'] * 0.3, box['width'] * 0.7)
                y = box['y'] + random.uniform(box['height'] * 0.3, box['height'] * 0.7)
                await self.page.mouse.move(x, y)
                await self._random_delay(50, 150)
            await locator.click()
        except:
            await locator.click()
    
    async def _human_type(self, locator, text):
        await locator.click()
        await self._random_delay(100, 300)
        for char in text:
            if random.random() < 0.1:
                await self._random_delay(300, 800)
            await locator.press_sequentially(char, delay=random.uniform(50, 200))
    
    async def _random_mouse_movements(self):
        try:
            for _ in range(random.randint(2, 5)):
                x = random.randint(100, 1800)
                y = random.randint(100, 1000)
                await self.page.mouse.move(x, y)
                await self._random_delay(100, 300)
        except:
            pass
    
    async def init_browser(self):
        if not self.playwright:
            self.playwright = await async_playwright().start()
            
            browser_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--window-size=1920,1080',
            ]
            
            try:
                self.browser = await self.playwright.chromium.launch(
                    headless=True,
                    args=browser_args,
                    channel='chrome'
                )
                print("✓ Chrome запущен")
            except:
                self.browser = await self.playwright.chromium.launch(
                    headless=True,
                    args=browser_args
                )
                print("✓ Chromium запущен")
            
            user_agent = self._get_random_user_agent()
            
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                locale='uk-UA',
                timezone_id='Europe/Kiev',
                user_agent=user_agent,
                geolocation={'latitude': 50.4501, 'longitude': 30.5234},
            )
            
            await self.context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.navigator.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'languages', { get: () => ['uk-UA', 'uk'] });
            """)
            
            self.page = await self.context.new_page()
            await self._load_cookies()
            await self._setup_page()
            await self._save_cookies()
    
    async def _setup_page(self):
        print("Настройка страницы...")
        await self.page.goto('https://www.dtek-krem.com.ua/ua/shutdowns', wait_until='networkidle', timeout=60000)
        await self._random_delay(3000, 5000)
        
        try:
            captcha_checkbox = self.page.locator('iframe[src*="checkbox"]')
            if await captcha_checkbox.count() > 0:
                print("⚠️ Обнаружена капча! Используйте веб-интерфейс.")
                for i in range(300):
                    await asyncio.sleep(1)
                    if await captcha_checkbox.count() == 0:
                        print("✓ Капча пройдена!")
                        await self._save_cookies()
                        break
        except:
            pass
        
        await self._random_delay(1500, 2500)
        
        try:
            close_btn = self.page.locator('button.m-attention__close')
            if await close_btn.count() > 0:
                await self._human_move_and_click(close_btn)
        except:
            pass
        
        city_input = self.page.locator('.discon-input-wrapper #city')
        await city_input.wait_for(state='visible', timeout=10000)
        await self._human_move_and_click(city_input)
        await city_input.clear()
        await self._human_type(city_input, 'княж')
        await self._random_delay(1800, 2500)
        
        city_option = self.page.locator('#cityautocomplete-list > div:nth-child(2)')
        await city_option.wait_for(state='visible', timeout=10000)
        await self._human_move_and_click(city_option)
        await self._random_delay(1000, 1800)
        
        street_input = self.page.locator('.discon-input-wrapper #street')
        await street_input.wait_for(state='visible', timeout=10000)
        await self._human_move_and_click(street_input)
        await street_input.clear()
        await self._human_type(street_input, 'киї')
        await self._random_delay(1800, 2500)
        
        street_option = self.page.locator('#streetautocomplete-list > div:nth-child(2)')
        await street_option.wait_for(state='visible', timeout=10000)
        await self._human_move_and_click(street_option)
        await self._random_delay(1000, 1800)
        
        house_input = self.page.locator('input#house_num')
        await house_input.wait_for(state='visible', timeout=10000)
        await self._human_move_and_click(house_input)
        await house_input.clear()
        await self._human_type(house_input, '168')
        await self._random_delay(1800, 2500)
        
        house_option = self.page.locator('#house_numautocomplete-list > div:first-child')
        await house_option.wait_for(state='visible', timeout=10000)
        await self._human_move_and_click(house_option)
        await self._random_delay(2500, 3500)
        
        try:
            update_elem = self.page.locator('span.update')
            await update_elem.wait_for(state='visible', timeout=15000)
            self.last_update_date = await update_elem.text_content()
            self.last_update_date = self.last_update_date.strip()
            print(f"✓ Дата обновления: {self.last_update_date}")
        except:
            self.last_update_date = "Невідомо"
        
        print("✅ Страница настроена!")
    
    async def _close_survey_if_present(self):
        """Закрывает опрос если он появился"""
        try:
            modal = self.page.locator('#modal-questionnaire-welcome-18 .modal__container')
            if await modal.is_visible():
                close_btn = self.page.locator('#modal-questionnaire-welcome-7 .modal__close')
                await close_btn.click()
                await asyncio.sleep(0.5)
        except:
            pass
    
    async def check_for_update(self):
        """Проверяет изменилась ли дата"""
        try:
            await self._close_survey_if_present()
            
            if random.random() < 0.3:
                await self._random_mouse_movements()
            
            update_elem = self.page.locator('span.update')
            await update_elem.wait_for(state='visible', timeout=10000)
            current_date = await update_elem.text_content()
            current_date = current_date.strip()
            
            print(f"Текущая дата: {current_date}, Последняя: {self.last_update_date}")
            
            if current_date != self.last_update_date:
                print("🔔 ОБНОВЛЕНИЕ ОБНАРУЖЕНО!")
                self.last_update_date = current_date
                await self._save_cookies()
                return True
            return False
        except Exception as e:
            print(f"Ошибка при проверке: {e}")
            return False
    
    def crop_screenshot(self, screenshot_bytes, top_crop=300, bottom_crop=400, left_crop=0, right_crop=0):
        """Обрезает скриншот"""
        try:
            image = Image.open(io.BytesIO(screenshot_bytes))
            width, height = image.size
            
            left = left_crop
            top = top_crop
            right = width - right_crop
            bottom = height - bottom_crop
            
            print(f"Обрезаю скриншот: {width}x{height} -> {right-left}x{bottom-top}")
            
            cropped = image.crop((left, top, right, bottom))
            
            output = io.BytesIO()
            cropped.save(output, format='PNG', optimize=True, quality=95)
            return output.getvalue()
        except Exception as e:
            print(f"⚠ Ошибка при обрезке скриншота: {e}")
            return screenshot_bytes
    
    async def make_screenshots(self):
    """Делает скриншоты"""
    try:
        await self._close_survey_if_present()
        await asyncio.sleep(1)
        
        print("Делаю скриншот основного графика...")
        # ИЗМЕНЕНИЕ 1: Добавлен таймаут для скриншота
        screenshot_main = await asyncio.wait_for(
            self.page.screenshot(full_page=True, type='png'),
            timeout=30
        )
        screenshot_main_cropped = self.crop_screenshot(screenshot_main, top_crop=300, bottom_crop=400)
        print("✓ Скриншот основного графика готов")
        
        print("Кликаю на второй график (завтра)...")
        second_date = None
        screenshot_tomorrow_cropped = None
        try:
            date_selector = self.page.locator('div.date:nth-child(2)')
            # ИЗМЕНЕНИЕ 2: Увеличен таймаут с 10000 до 15000
            await date_selector.wait_for(state='visible', timeout=15000)
            
            second_date = await date_selector.text_content()
            second_date = second_date.strip()
            print(f"Дата второго графика: {second_date}")
            
            await date_selector.click()
            # ИЗМЕНЕНИЕ 3: Увеличена задержка с 4 до 5 секунд
            await asyncio.sleep(5)
            
            await self._close_survey_if_present()
            
            print("Делаю скриншот второго графика...")
            # ИЗМЕНЕНИЕ 4: Добавлен таймаут для скриншота
            screenshot_tomorrow = await asyncio.wait_for(
                self.page.screenshot(full_page=True, type='png'),
                timeout=30
            )
            screenshot_tomorrow_cropped = self.crop_screenshot(screenshot_tomorrow, top_crop=300, bottom_crop=400)
            print("✓ Скриншот второго графика готов")
            
            print("Возвращаюсь на первый график...")
            first_date = self.page.locator('div.date:nth-child(1)')
            await first_date.click()
            await asyncio.sleep(2)
            print("✓ Вернулся на первый график")
            
        except Exception as e:
            print(f"⚠ Не удалось получить второй график: {e}")
        
        return {
            'screenshot_main': screenshot_main_cropped,
            'screenshot_tomorrow': screenshot_tomorrow_cropped,
            'update_date': self.last_update_date,
            'second_date': second_date,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"✘ Ошибка при создании скриншотов: {e}")
        raise

    
    async def close_browser(self):
        """Закрытие браузера"""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

checker = DTEKChecker()

async def get_last_check():
    """Получает данные последней проверки из БД"""
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT update_date, created_at FROM dtek_checks ORDER BY created_at DESC LIMIT 1'
            )
            if row:
                return {'update_date': row['update_date'], 'created_at': row['created_at']}
    except Exception as e:
        print(f"Ошибка при получении данных из БД: {e}")
    return None

async def save_check(update_date):
    """Сохраняет данные проверки в БД"""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO dtek_checks (update_date, created_at) VALUES ($1, $2)',
                update_date, datetime.now()
            )
        print(f"✓ Данные сохранены в БД: {update_date}")
    except Exception as e:
        print(f"❌ Ошибка при сохранении в БД: {e}")

@bot.event
async def on_ready():
    print(f'✓ {bot.user} подключен к Discord!')
    print(f'✓ Мониторинг канала: {CHANNEL_ID}')
    print(f'✓ Интервал проверки: каждые 5 минут')
    print(f'🌐 Веб-интерфейс для прохождения капчи запущен на порту {PORT}')
    print(f'🥷 STEALTH MODE активирован')
    await init_db_pool()
    await start_web_server()
    
    # НЕ инициализируем браузер автоматически - пользователь сделает это через веб-интерфейс
    print("💡 Откройте веб-интерфейс и нажмите 'Инициализировать браузер'")
    print(f"🌐 URL: http://localhost:{PORT}")
    print("🎉 Бот готов к работе!")
    
    check_schedule.start()

@tasks.loop(minutes=5)
async def check_schedule():
    """Периодическая проверка каждые 5 минут"""
    channel = None
    try:
        # Пропускаем если браузер не инициализирован
        if not checker.browser or not checker.page:
            print("⏭️ Браузер не инициализирован, пропускаю проверку")
            return
        
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            print(f"✘ Канал {CHANNEL_ID} не найден!")
            return
        
        print(f"\n{'='*50}")
        print(f"[{datetime.now()}] Запуск автоматической проверки...")
        print(f"{'='*50}")
        
        has_update = await checker.check_for_update()
        
        if not has_update:
            print(f"ℹ️ Без изменений")
            print(f"{'='*50}\n")
            return
        
        # ИЗМЕНЕНИЕ 5: Увеличен таймаут со 120 до 180 секунд (3 минуты)
        result = await asyncio.wait_for(checker.make_screenshots(), timeout=180)
        await save_check(result['update_date'])
        
        # ВЕСЬ ОСТАЛЬНОЙ КОД ОСТАЕТСЯ БЕЗ ИЗМЕНЕНИЙ!
        embed = discord.Embed(
            title="⚡ Графік відключень ДТЕК Київські регіональні електромережі",
            description="**📍 Адреса:** с. Книжичі, вул. Київська, 168",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )
        
        if result['update_date']:
            embed.add_field(
                name="🕐 Дата оновлення на сайті",
                value=f"`{result['update_date']}`",
                inline=False
            )
        
        embed.add_field(
            name="✅ Статус",
            value="**🔔 ІНФОРМАЦІЯ ОНОВИЛАСЬ!**",
            inline=False
        )
        embed.set_footer(text="Нова інформація • Автоматична перевірка")
        
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_main = discord.File(
            io.BytesIO(result['screenshot_main']), 
            filename=f"dtek_today_{timestamp_str}.png"
        )
        
        await channel.send(embed=embed, file=file_main)
        
        if result['screenshot_tomorrow']:
            embed_tomorrow = discord.Embed(
                title="📅 Графік відключень на завтра",
                description=f"**📍 Адреса:** с. Книжичі, вул. Київська, 168\n**📆 Дата:** {result['second_date'] or 'Завтра'}",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            file_tomorrow = discord.File(
                io.BytesIO(result['screenshot_tomorrow']), 
                filename=f"dtek_tomorrow_{timestamp_str}.png"
            )
            
            await channel.send(embed=embed_tomorrow, file=file_tomorrow)
        
        print(f"✓ Сообщение отправлено в Discord")
        print(f"{'='*50}\n")
        
    except asyncio.TimeoutError:
        # ИЗМЕНЕНИЕ 6: Добавлено специальное сообщение для таймаута
        print(f"⏱️ ТАЙМАУТ: Операция заняла больше 3 минут")
        print(f"{'='*50}\n")
        if channel:
            try:
                error_embed = discord.Embed(
                    title="⏱️ Таймаут операції",
                    description="Перевірка зайняла більше 3 хвилин. Можливо, сайт повільно завантажується.",
                    color=discord.Color.orange(),
                    timestamp=datetime.now()
                )
                await channel.send(embed=error_embed)
            except:
                pass
    except Exception as e:
        print(f"✘ Ошибка в check_schedule: {e}")
        import traceback
        traceback.print_exc()
        
        if channel:
            try:
                error_embed = discord.Embed(
                    title="⚠️ Помилка перевірки",
                    description=f"Не вдалося виконати перевірку.\n```{str(e)[:200]}```",
                    color=discord.Color.red(),
                    timestamp=datetime.now()
                )
                await channel.send(embed=error_embed)
            except:
                pass

@check_schedule.before_loop
async def before_check_schedule():
    """Ждем, пока бот будет готов"""
    await bot.wait_until_ready()
    print("⏳ Ожидание готовности бота...")

@bot.command(name='check')
async def manual_check(ctx):
    """Ручная проверка по команде !check"""
    if not checker.browser or not checker.page:
        await ctx.send("✘ Браузер не ініціалізовано. Відкрийте веб-інтерфейс та натисніть 'Ініціалізувати браузер'")
        return
    
    await ctx.send("⏳ Починаю перевірку графіка відключень...")
    
    try:
        # ИЗМЕНЕНИЕ 7: Увеличен таймаут со 120 до 180 секунд
        result = await asyncio.wait_for(checker.make_screenshots(), timeout=180)
        await save_check(result['update_date'])
        
        # ВЕСЬ ОСТАЛЬНОЙ КОД ОСТАЕТСЯ БЕЗ ИЗМЕНЕНИЙ!
        embed = discord.Embed(
            title="⚡ Графік відключень ДТЕК (Ручна перевірка)",
            description="**📍 Адреса:** с. Книжичі, вул. Київська, 168",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        
        if result['update_date']:
            embed.add_field(
                name="🕐 Дата оновлення на сайті",
                value=f"`{result['update_date']}`",
                inline=False
            )
        
        embed.set_footer(text="Ручна перевірка • Запущено командою !check")
        
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_main = discord.File(
            io.BytesIO(result['screenshot_main']), 
            filename=f"dtek_manual_today_{timestamp_str}.png"
        )
        
        await ctx.send(embed=embed, file=file_main)
        
        if result['screenshot_tomorrow']:
            embed_tomorrow = discord.Embed(
                title="📅 Графік відключень на завтра",
                description=f"**📍 Адреса:** с. Книжичі, вул. Київська, 168\n**📆 Дата:** {result['second_date'] or 'Завтра'}",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            file_tomorrow = discord.File(
                io.BytesIO(result['screenshot_tomorrow']), 
                filename=f"dtek_manual_tomorrow_{timestamp_str}.png"
            )
            
            await ctx.send(embed=embed_tomorrow, file=file_tomorrow)
        
    except asyncio.TimeoutError:
        error_embed = discord.Embed(
            title="⏱️ Таймаут",
            description="Перевірка зайняла більше 3 хвилин.",
            color=discord.Color.orange()
        )
        await ctx.send(embed=error_embed)
    except Exception as e:
        error_embed = discord.Embed(
            title="✘ Помилка",
            description=f"```{str(e)[:500]}```",
            color=discord.Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command(name='info')
async def bot_info(ctx):
    """Информация о боте"""
    embed = discord.Embed(
        title="ℹ️ Інформація про бота",
        description="Бот для автоматичного моніторингу графіків відключень ДТЕК",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="📍 Адреса моніторингу",
        value="с. Книжичі, вул. Київська, 168",
        inline=False
    )
    
    embed.add_field(
        name="⏱️ Інтервал перевірки",
        value="Кожні 5 хвилин",
        inline=True
    )
    
    browser_status = "✅ Відкритий" if checker.browser else "❌ Закритий"
    embed.add_field(
        name="🌐 Статус браузера",
        value=browser_status,
        inline=True
    )
    
    cookies_status = "✅ Збережено" if os.path.exists(checker.cookies_file) else "❌ Відсутні"
    embed.add_field(
        name="🍪 Куки",
        value=cookies_status,
        inline=True
    )
    
    if checker.last_update_date:
        embed.add_field(
            name="🕐 Остання дата на сайті",
            value=f"`{checker.last_update_date}`",
            inline=False
        )
    
    embed.add_field(
        name="🌐 Веб-інтерфейс",
        value=f"Порт: {PORT}\nДля проходження капчі",
        inline=False
    )
    
    embed.add_field(
        name="📝 Команди",
        value="`!check` - Ручна перевірка\n`!info` - Інформація\n`!status` - Детальний статус\n`!stop` - Зупинити (адміни)",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name='status')
async def bot_status(ctx):
    """Детальный статус бота"""
    embed = discord.Embed(
        title="🔍 Детальний статус бота",
        color=discord.Color.purple(),
        timestamp=datetime.now()
    )
    
    playwright_status = "✅ Запущен" if checker.playwright else "❌ Не запущен"
    browser_status = "✅ Открыт" if checker.browser else "❌ Закрыт"
    page_status = "✅ Загружена" if checker.page else "❌ Не загружена"
    
    embed.add_field(name="Playwright", value=playwright_status, inline=True)
    embed.add_field(name="Browser", value=browser_status, inline=True)
    embed.add_field(name="Page", value=page_status, inline=True)
    
    db_status = "✅ Підключено" if db_pool else "❌ Не підключено"
    embed.add_field(name="База даних", value=db_status, inline=False)
    
    task_status = "✅ Запущено" if check_schedule.is_running() else "❌ Зупинено"
    embed.add_field(name="Автоматична перевірка", value=task_status, inline=False)
    
    if checker.last_update_date:
        embed.add_field(name="📅 Дата на сайті", value=f"`{checker.last_update_date}`", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='stop')
@commands.has_permissions(administrator=True)
async def stop_bot(ctx):
    """Остановка бота"""
    await ctx.send("🛑 Зупиняю бота...")
    check_schedule.cancel()
    try:
        await checker._save_cookies()
        await checker.close_browser()
    except:
        pass
    await close_db_pool()
    await bot.close()

if __name__ == '__main__':
    try:
        print("🤖 Запуск Discord бота DTEK с веб-интерфейсом...")
        print(f"📅 Дата: {datetime.now()}")
        print("🌐 Веб-интерфейс для управления браузером включен")
        bot.run(DISCORD_TOKEN)
    except KeyboardInterrupt:
        print("\n🛑 Остановка бота...")
    finally:
        try:
            asyncio.run(checker._save_cookies())
            asyncio.run(checker.close_browser())
            asyncio.run(close_db_pool())
        except:
            pass

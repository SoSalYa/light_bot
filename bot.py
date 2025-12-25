import discord
from discord.ext import commands, tasks
from discord.ui import Button, View
import asyncio
from playwright.async_api import async_playwright
import os
from datetime import datetime, timedelta
import io
import asyncpg
from PIL import Image
from aiohttp import web
import random
import json
import base64
import hashlib
import sys
from collections import deque
import pytz

# Конфігурація
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))
DATABASE_URL = os.getenv('DATABASE_URL')
PORT = int(os.getenv('PORT', 10000))

# Часовий пояс України (UTC+2/+3)
UKRAINE_TZ = pytz.timezone('Europe/Kiev')

# Database pool
db_pool = None

# Логування в пам'яті для веб-інтерфейсу
log_buffer = deque(maxlen=500)

# Глобальна змінна для зберігання поточної капчі
current_captcha = None

def log(message):
    """Логування з виводом в консоль і збереженням для веб-інтерфейсу"""
    now = datetime.now(UKRAINE_TZ)
    timestamp = now.strftime('%H:%M:%S')
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    log_buffer.append(log_entry)
    sys.stdout.flush()

# Створення бота
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

class CaptchaState:
    """Клас для зберігання стану капчі"""
    def __init__(self):
        self.active = False
        self.screenshot = None
        self.selected_images = []
        self.message = None
        self.view = None
        self.stage = 1  # Етап капчі (1 або 2)
        self.resolver_event = asyncio.Event()
        self.resolved = False

class CaptchaView(View):
    """Інтерактивні кнопки для вирішення капчі"""
    def __init__(self, captcha_state):
        super().__init__(timeout=300)  # 5 хвилин таймаут
        self.captcha_state = captcha_state
        
        # 9 кнопок для вибору картинок (3x3)
        for i in range(9):
            button = Button(
                label=str(i + 1),
                style=discord.ButtonStyle.secondary,
                custom_id=f"img_{i}"
            )
            button.callback = self.create_callback(i)
            self.add_item(button)
        
        # Кнопка "Перевірити"
        verify_button = Button(
            label="✅ Перевірити",
            style=discord.ButtonStyle.success,
            custom_id="verify",
            row=3
        )
        verify_button.callback = self.verify_callback
        self.add_item(verify_button)
        
        # Кнопка "Скинути"
        reset_button = Button(
            label="🔄 Скинути",
            style=discord.ButtonStyle.danger,
            custom_id="reset",
            row=3
        )
        reset_button.callback = self.reset_callback
        self.add_item(reset_button)
    
    def create_callback(self, index):
        async def callback(interaction: discord.Interaction):
            if index in self.captcha_state.selected_images:
                self.captcha_state.selected_images.remove(index)
                self.children[index].style = discord.ButtonStyle.secondary
            else:
                self.captcha_state.selected_images.append(index)
                self.children[index].style = discord.ButtonStyle.primary
            
            await interaction.response.edit_message(
                content=f"🧩 **Капча - Етап {self.captcha_state.stage}**\n"
                        f"Оберіть всі картинки з потрібним об'єктом\n"
                        f"Обрано: {len(self.captcha_state.selected_images)} картинок",
                view=self
            )
        return callback
    
    async def verify_callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=f"⏳ Перевіряю вибір ({len(self.captcha_state.selected_images)} картинок)...",
            view=None
        )
        self.captcha_state.resolved = True
        self.captcha_state.resolver_event.set()
    
    async def reset_callback(self, interaction: discord.Interaction):
        self.captcha_state.selected_images = []
        for i in range(9):
            self.children[i].style = discord.ButtonStyle.secondary
        
        await interaction.response.edit_message(
            content=f"🧩 **Капча - Етап {self.captcha_state.stage}**\n"
                    f"Оберіть всі картинки з потрібним об'єктом\n"
                    f"Обрано: 0 картинок",
            view=self
        )

async def init_db_pool():
    """Ініціалізація connection pool для PostgreSQL"""
    global db_pool
    if not db_pool:
        db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
            command_timeout=60
        )
        log("✓ Database pool створено")
        
        async with db_pool.acquire() as conn:
            # Створюємо основну таблицю
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS dtek_checks (
                    id SERIAL PRIMARY KEY,
                    update_date TEXT,
                    schedule_hash TEXT,
                    schedule_data JSONB,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Додаємо нові колонки якщо їх немає (міграція)
            try:
                await conn.execute('''
                    ALTER TABLE dtek_checks 
                    ADD COLUMN IF NOT EXISTS schedule_tomorrow_hash TEXT
                ''')
                log("✓ Колонка schedule_tomorrow_hash додана/існує")
            except Exception as e:
                log(f"⚠️ Помилка додавання schedule_tomorrow_hash: {e}")
            
            try:
                await conn.execute('''
                    ALTER TABLE dtek_checks 
                    ADD COLUMN IF NOT EXISTS schedule_tomorrow_data JSONB
                ''')
                log("✓ Колонка schedule_tomorrow_data додана/існує")
            except Exception as e:
                log(f"⚠️ Помилка додавання schedule_tomorrow_data: {e}")
        
        log("✓ Таблиця БД готова")

async def close_db_pool():
    """Закриття connection pool"""
    global db_pool
    if db_pool:
        await db_pool.close()
        log("✓ Database pool закрито")

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
                max-width: 1800px;
                margin: 0 auto;
                display: grid;
                grid-template-columns: 1fr 400px;
                gap: 20px;
            }
            
            .left-panel {
                display: flex;
                flex-direction: column;
                gap: 20px;
            }
            
            .right-panel {
                display: flex;
                flex-direction: column;
                gap: 20px;
                position: sticky;
                top: 20px;
                height: fit-content;
            }
            
            .header {
                text-align: center;
                color: white;
                margin-bottom: 30px;
                grid-column: 1 / -1;
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
            
            .control-panel, .viewer, .info-panel, .instructions, .logs-panel {
                background: white;
                border-radius: 15px;
                padding: 20px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            }
            
            .control-panel h2, .viewer h2, .info-panel h2, .instructions h3, .logs-panel h2 {
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
            
            .info-grid {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
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
                border-left: 4px solid #667eea;
            }
            .instructions ul {
                margin-left: 20px;
                line-height: 1.8;
            }
            
            .logs-panel {
                max-height: calc(100vh - 100px);
                display: flex;
                flex-direction: column;
            }
            .logs-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px;
            }
            .logs-container {
                background: #1e1e1e;
                border-radius: 8px;
                padding: 15px;
                font-family: 'Courier New', monospace;
                font-size: 12px;
                color: #00ff00;
                overflow-y: auto;
                flex: 1;
                max-height: 70vh;
            }
            .log-entry {
                margin-bottom: 5px;
                line-height: 1.4;
                word-wrap: break-word;
            }
            .log-entry:hover {
                background: rgba(255,255,255,0.1);
            }
            .logs-container::-webkit-scrollbar {
                width: 8px;
            }
            .logs-container::-webkit-scrollbar-track {
                background: #2d2d2d;
                border-radius: 4px;
            }
            .logs-container::-webkit-scrollbar-thumb {
                background: #667eea;
                border-radius: 4px;
            }
            .clear-logs-btn {
                padding: 6px 12px;
                font-size: 12px;
                background: #f44336;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
            }
            
            @media (max-width: 1400px) {
                .container {
                    grid-template-columns: 1fr;
                }
                .right-panel {
                    position: relative;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 DTEK Bot Remote Control</h1>
                <span class="status" id="status">⚪ Connecting...</span>
            </div>
            
            <div class="left-panel">
                <div class="instructions">
                    <h3>📖 Як використовувати:</h3>
                    <ul>
                        <li><strong>Клікайте по скріншоту</strong> - кліки передаються в браузер бота</li>
                        <li><strong>Оновити скріншот</strong> - отримати актуальне зображення</li>
                        <li><strong>Пройти капчу</strong> - клікайте по елементам капчі прямо на скріншоті</li>
                        <li>Скріншоти оновлюються автоматично кожні 3 секунди</li>
                        <li><strong>Логи справа</strong> - показують що робить бот в реальному часі</li>
                    </ul>
                </div>
                
                <div class="control-panel">
                    <h2>🎮 Панель управління</h2>
                    <div class="buttons">
                        <button class="btn-primary" onclick="refreshScreenshot()">🔄 Оновити скріншот</button>
                        <button class="btn-success" onclick="initBrowser()">🚀 Ініціалізувати браузер</button>
                        <button class="btn-info" onclick="manualCheck()">✅ Зробити перевірку</button>
                        <button class="btn-danger" onclick="clearCookies()">🍪 Очистити куки</button>
                    </div>
                </div>
                
                <div class="viewer">
                    <h2>👁️ Віддалений перегляд браузера</h2>
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
                            <h3>Остання дата</h3>
                            <p id="last-update">-</p>
                        </div>
                        <div class="info-card">
                            <h3>Куки</h3>
                            <p id="cookies-status">-</p>
                        </div>
                        <div class="info-card">
                            <h3>Останнє оновлення</h3>
                            <p id="last-refresh">-</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="right-panel">
                <div class="logs-panel">
                    <div class="logs-header">
                        <h2>📋 Логи бота</h2>
                        <button class="clear-logs-btn" onclick="clearLogsDisplay()">🗑️ Очистити</button>
                    </div>
                    <div class="logs-container" id="logs">
                        <div class="log-entry">Завантаження логів...</div>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            let autoRefresh = null;
            let imageNaturalWidth = 0;
            let imageNaturalHeight = 0;
            let logsAutoScroll = true;
            
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
                document.getElementById('status').textContent = '⏳ Ініціалізація...';
                try {
                    const data = await request('/api/init');
                    alert(data.message);
                    await updateStatus();
                    await refreshScreenshot();
                } catch (e) {
                    alert('Помилка: ' + e.message);
                }
            }
            
            async function manualCheck() {
                document.getElementById('status').textContent = '⏳ Перевірка...';
                try {
                    const data = await request('/api/check');
                    alert(data.message);
                    await refreshScreenshot();
                } catch (e) {
                    alert('Помилка: ' + e.message);
                }
            }
            
            async function clearCookies() {
                try {
                    const data = await request('/api/clear-cookies', 'POST');
                    alert(data.message);
                    await updateStatus();
                } catch (e) {
                    alert('Помилка: ' + e.message);
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
                    if (data.browser === '✅ Відкритий') {
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
            
            async function updateLogs() {
                try {
                    const data = await request('/api/logs');
                    const logsContainer = document.getElementById('logs');
                    
                    if (data.logs && data.logs.length > 0) {
                        const shouldScroll = logsContainer.scrollHeight - logsContainer.scrollTop <= logsContainer.clientHeight + 50;
                        
                        logsContainer.innerHTML = data.logs.map(log => 
                            `<div class="log-entry">${escapeHtml(log)}</div>`
                        ).join('');
                        
                        if (shouldScroll && logsAutoScroll) {
                            logsContainer.scrollTop = logsContainer.scrollHeight;
                        }
                    }
                } catch (e) {
                    console.error('Logs update error:', e);
                }
            }
            
            function escapeHtml(text) {
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }
            
            function clearLogsDisplay() {
                document.getElementById('logs').innerHTML = '<div class="log-entry">Логи очищено локально</div>';
            }
            
            document.getElementById('logs').addEventListener('scroll', (e) => {
                const container = e.target;
                logsAutoScroll = container.scrollHeight - container.scrollTop <= container.clientHeight + 50;
            });
            
            function startAutoRefresh() {
                autoRefresh = setInterval(() => {
                    refreshScreenshot();
                    updateStatus();
                    updateLogs();
                }, 3000);
            }
            
            window.onload = async () => {
                await updateStatus();
                await updateLogs();
                await refreshScreenshot();
                startAutoRefresh();
            };
        </script>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def handle_screenshot(request):
    """API: Получити скріншот браузера"""
    try:
        if not checker.page:
            return web.json_response({'error': 'Browser not initialized'}, status=400)
        
        screenshot = await checker.page.screenshot(type='png', full_page=True)
        screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
        
        return web.json_response({
            'screenshot': screenshot_base64,
            'timestamp': datetime.now(UKRAINE_TZ).isoformat()
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def handle_click(request):
    """API: Передати клік в браузер"""
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
    """API: Ініціалізувати браузер"""
    try:
        await checker.init_browser()
        return web.json_response({
            'message': 'Браузер ініціалізовано успішно!',
            'success': True
        })
    except Exception as e:
        return web.json_response({
            'message': f'Помилка ініціалізації: {str(e)}',
            'success': False
        }, status=500)

async def handle_check(request):
    """API: Виконати перевірку"""
    try:
        result = await checker.make_screenshots()
        return web.json_response({
            'message': 'Перевірка виконана успішно!',
            'success': True,
            'update_date': result.get('update_date')
        })
    except Exception as e:
        return web.json_response({
            'message': f'Помилка перевірки: {str(e)}',
            'success': False
        }, status=500)

async def handle_clear_cookies(request):
    """API: Очистити куки"""
    try:
        if os.path.exists(checker.cookies_file):
            os.remove(checker.cookies_file)
        return web.json_response({
            'message': 'Куки успішно видалено',
            'success': True
        })
    except Exception as e:
        return web.json_response({
            'message': f'Помилка: {str(e)}',
            'success': False
        }, status=500)

async def handle_logs(request):
    """API: Отримати останні логи"""
    return web.json_response({
        'logs': list(log_buffer),
        'timestamp': datetime.now(UKRAINE_TZ).isoformat()
    })

async def handle_status(request):
    """API: Получити статус бота"""
    browser_status = "✅ Відкритий" if checker.browser else "✖️ Закритий"
    cookies_status = "✅ Є" if os.path.exists(checker.cookies_file) else "✖️ Немає"
    
    return web.json_response({
        'browser': browser_status,
        'last_update': checker.last_update_date,
        'cookies': cookies_status
    })

async def start_web_server():
    """Запуск веб-сервера з VNC інтерфейсом"""
    app = web.Application()
    
    app.router.add_get('/', handle_root)
    app.router.add_get('/health', handle_health)
    
    app.router.add_get('/api/screenshot', handle_screenshot)
    app.router.add_post('/api/click', handle_click)
    app.router.add_get('/api/init', handle_init)
    app.router.add_get('/api/check', handle_check)
    app.router.add_post('/api/clear-cookies', handle_clear_cookies)
    app.router.add_get('/api/status', handle_status)
    app.router.add_get('/api/logs', handle_logs)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    log(f"✓ Web server started on port {PORT}")

class DTEKChecker:
    def __init__(self):
        self.browser = None
        self.context = None
        self.playwright = None
        self.page = None
        self.last_update_date = None
        self.cookies_file = 'dtek_cookies.json'
        self.captcha_attempts = 0
        self.max_captcha_attempts = 3
    
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
                print("✓ Куки збережено")
        except Exception as e:
            print(f"⚠ Не вдалось зберегти куки: {e}")
    
    async def _load_cookies(self):
        try:
            if os.path.exists(self.cookies_file):
                with open(self.cookies_file, 'r') as f:
                    cookies = json.load(f)
                await self.context.add_cookies(cookies)
                print("✓ Куки завантажено")
                return True
        except Exception as e:
            print(f"⚠ Не вдалось завантажити куки: {e}")
        return False
    
    async def _random_delay(self, min_ms=100, max_ms=500):
        await asyncio.sleep(random.uniform(min_ms/1000, max_ms/1000))
    
    async def _human_move_and_click(self, locator):
        """Більш людяноподібний клік з рухом миші"""
        try:
            box = await locator.bounding_box()
            if box:
                # Спочатку рухаємось до випадкової точки поруч
                pre_x = box['x'] + random.uniform(-50, box['width'] + 50)
                pre_y = box['y'] + random.uniform(-20, box['height'] + 20)
                await self.page.mouse.move(pre_x, pre_y)
                await self._random_delay(50, 150)
                
                # Потім до самої кнопки
                x = box['x'] + random.uniform(box['width'] * 0.3, box['width'] * 0.7)
                y = box['y'] + random.uniform(box['height'] * 0.3, box['height'] * 0.7)
                await self.page.mouse.move(x, y)
                await self._random_delay(50, 150)
            await locator.click()
            await self._random_delay(200, 400)
        except:
            await locator.click()
    
    async def _human_type(self, locator, text):
        """Більш людяноподібне введення тексту"""
        await locator.click()
        await self._random_delay(100, 300)
        for char in text:
            if random.random() < 0.1:
                await self._random_delay(300, 800)
            await locator.press_sequentially(char, delay=random.uniform(50, 200))
    
    async def _random_mouse_movements(self):
        """Випадкові рухи миші для імітації людини"""
        try:
            for _ in range(random.randint(2, 5)):
                x = random.randint(100, 1800)
                y = random.randint(100, 1000)
                await self.page.mouse.move(x, y)
                await self._random_delay(100, 300)
        except:
            pass
    
    async def _close_attention_popup(self):
        """Закриває спливаюче вікно "Шановні клієнти!" про відключення"""
        try:
            log("🔍 Перевіряю наявність спливаючого вікна...")
            
            # Пробуємо закрити через кнопку .m-attention__close
            close_btn = self.page.locator('button.m-attention__close')
            if await close_btn.count() > 0 and await close_btn.is_visible():
                log("✓ Знайдено спливаюче вікно - закриваю")
                await self._human_move_and_click(close_btn)
                await asyncio.sleep(1)
                log("✓ Спливаюче вікно закрито")
                return True
            
            # Альтернативний варіант - пошук по тексту
            close_x = self.page.locator('button:has-text("×")').first
            if await close_x.count() > 0:
                try:
                    if await close_x.is_visible(timeout=1000):
                        log("✓ Знайдено кнопку × - закриваю")
                        await self._human_move_and_click(close_x)
                        await asyncio.sleep(1)
                        log("✓ Вікно закрито через ×")
                        return True
                except:
                    pass
            
            log("ℹ️ Спливаюче вікно не знайдено")
            return False
        except Exception as e:
            log(f"⚠️ Помилка закриття спливаючого вікна: {e}")
            return False
    
    async def _detect_captcha(self):
        """Виявлення ТІЛЬКИ реальної капчі (iframe recaptcha) - НЕ спливаючі вікна!"""
        try:
            log("🔍 Перевіряю наявність капчі (iframe)...")
            
            # Шукаємо ТІЛЬКИ iframe з recaptcha/captcha/checkbox
            captcha_iframes = [
                'iframe[src*="recaptcha"]',
                'iframe[src*="captcha"]',
                'iframe[title*="reCAPTCHA"]',
                'iframe[src*="checkbox"]'
            ]
            
            for selector in captcha_iframes:
                elements = self.page.locator(selector)
                count = await elements.count()
                if count > 0:
                    log(f"🧩 ВИЯВЛЕНО РЕАЛЬНУ КАПЧУ: {selector} (кількість: {count})")
                    return True
            
            log("✓ Капча (iframe) не виявлена")
            return False
        except Exception as e:
            log(f"⚠️ Помилка перевірки капчі: {e}")
            return False
    
    async def _handle_captcha_interactive(self, channel):
        """Інтерактивна обробка капчі через Discord"""
        global current_captcha
        
        try:
            log("🧩 Початок обробки капчі...")
            
            # Робимо скріншот капчі
            captcha_screenshot = await self.page.screenshot(type='png', full_page=False)
            
            # Створюємо стан капчі
            captcha_state = CaptchaState()
            captcha_state.active = True
            captcha_state.screenshot = captcha_screenshot
            current_captcha = captcha_state
            
            # Відправляємо в Discord з кнопками
            file = discord.File(
                io.BytesIO(captcha_screenshot),
                filename=f"captcha_{datetime.now().strftime('%H%M%S')}.png"
            )
            
            view = CaptchaView(captcha_state)
            captcha_state.view = view
            
            embed = discord.Embed(
                title="🧩 Виявлено капчу!",
                description="Оберіть всі картинки з потрібним об'єктом та натисніть 'Перевірити'",
                color=discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(
                name="📝 Інструкція",
                value="1. Натискайте на номери картинок (1-9)\n"
                      "2. Обрані картинки стануть синіми\n"
                      "3. Натисніть '✅ Перевірити' коли готово\n"
                      "4. Використовуйте '🔄 Скинути' щоб почати знову",
                inline=False
            )
            
            message = await channel.send(embed=embed, file=file, view=view)
            captcha_state.message = message
            
            # Чекаємо на вирішення
            log("⏳ Очікую вирішення капчі користувачем...")
            await asyncio.wait_for(captcha_state.resolver_event.wait(), timeout=300)
            
            if captcha_state.resolved:
                log(f"✓ Користувач обрав {len(captcha_state.selected_images)} картинок")
                
                # Клікаємо по обраним картинкам
                await self._click_captcha_images(captcha_state.selected_images)
                
                # Чекаємо трохи
                await asyncio.sleep(2)
                
                # Перевіряємо чи потрібен другий етап
                still_captcha = await self._detect_captcha()
                
                if still_captcha:
                    log("🧩 Капча має другий етап...")
                    captcha_state.stage = 2
                    captcha_state.selected_images = []
                    captcha_state.resolved = False
                    captcha_state.resolver_event.clear()
                    
                    # Повторюємо процес для другого етапу
                    captcha_screenshot2 = await self.page.screenshot(type='png', full_page=False)
                    file2 = discord.File(
                        io.BytesIO(captcha_screenshot2),
                        filename=f"captcha_stage2_{datetime.now().strftime('%H%M%S')}.png"
                    )
                    
                    view2 = CaptchaView(captcha_state)
                    
                    embed2 = discord.Embed(
                        title="🧩 Капча - Етап 2",
                        description="Оберіть картинки для другого етапу",
                        color=discord.Color.orange(),
                        timestamp=datetime.utcnow()
                    )
                    
                    await message.edit(embed=embed2, attachments=[file2], view=view2)
                    
                    await asyncio.wait_for(captcha_state.resolver_event.wait(), timeout=300)
                    
                    if captcha_state.resolved:
                        await self._click_captcha_images(captcha_state.selected_images)
                        await asyncio.sleep(2)
                
                # Перевіряємо успішність
                success = await self._verify_page_loaded()
                
                if success:
                    log("✅ Капча успішно пройдена!")
                    success_embed = discord.Embed(
                        title="✅ Капча пройдена!",
                        description="Сторінка успішно завантажена",
                        color=discord.Color.green(),
                        timestamp=datetime.utcnow()
                    )
                    await message.edit(embed=success_embed, view=None)
                    self.captcha_attempts = 0
                    return True
                else:
                    log("❌ Капча не пройдена")
                    fail_embed = discord.Embed(
                        title="❌ Капча не пройдена",
                        description="Спробуємо ще раз...",
                        color=discord.Color.red(),
                        timestamp=datetime.utcnow()
                    )
                    await message.edit(embed=fail_embed, view=None)
                    return False
            
            return False
            
        except asyncio.TimeoutError:
            log("⏰ Таймаут очікування вирішення капчі")
            timeout_embed = discord.Embed(
                title="⏰ Час вийшов",
                description="Капча не була вирішена протягом 5 хвилин",
                color=discord.Color.dark_gray(),
                timestamp=datetime.utcnow()
            )
            if current_captcha and current_captcha.message:
                await current_captcha.message.edit(embed=timeout_embed, view=None)
            return False
        except Exception as e:
            log(f"❌ Помилка обробки капчі: {e}")
            return False
        finally:
            current_captcha = None
    
    async def _click_captcha_images(self, selected_indices):
        """Клік по обраним картинкам капчі"""
        try:
            log(f"🖱️ Клікаю по обраним картинкам: {selected_indices}")
            
            # Для сітки 3x3 обчислюємо координати
            for index in selected_indices:
                row = index // 3
                col = index % 3
                
                # Обчислюємо координати (приблизно, залежить від розташування капчі)
                # Це потрібно буде налаштувати під конкретну капчу
                x = 30 + col * 100
                y = 100 + row * 100
                
                log(f"  Клік на картинку {index+1}: ({x}, {y})")
                await self.page.mouse.click(x, y)
                await self._random_delay(200, 500)
            
            # Клік на кнопку перевірки
            verify_button = self.page.locator('[id*="recaptcha-verify-button"]')
            if await verify_button.count() > 0:
                log("✓ Натискаю кнопку перевірки")
                await verify_button.click()
                await asyncio.sleep(2)
                
        except Exception as e:
            log(f"⚠️ Помилка кліку по капчі: {e}")
    
    async def _verify_page_loaded(self):
        """Перевірка чи сторінка завантажилась правильно"""
        try:
            log("🔍 Перевіряю чи сторінка завантажена...")
            
            # Перевіряємо відсутність капчі
            has_captcha = await self._detect_captcha()
            if has_captcha:
                log("❌ Капча все ще присутня")
                return False
            
            # Перевіряємо наявність поля вводу міста
            city_input = self.page.locator('.discon-input-wrapper #city')
            try:
                await city_input.wait_for(state='visible', timeout=5000)
                log("✓ Поле вводу міста знайдено - сторінка завантажена")
                return True
            except:
                log("❌ Поле вводу міста не знайдено")
                return False
            
        except Exception as e:
            log(f"⚠️ Помилка перевірки сторінки: {e}")
            return False
    
    async def _close_survey_if_present(self):
        """Закриває опрос якщо він з'явився"""
        try:
            modal_found = await self.page.evaluate("""
                () => {
                    const modals = document.querySelectorAll('[id^="modal-questionnaire-welcome-"]');
                    for (const modal of modals) {
                        const style = window.getComputedStyle(modal);
                        if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                            return modal.id;
                        }
                    }
                    return null;
                }
            """)
            
            if modal_found:
                log(f"✓ Знайдено модальне вікно опросу: {modal_found}")
                close_selector = f"#{modal_found} .modal__close"
                try:
                    close_btn = self.page.locator(close_selector).first
                    if await close_btn.is_visible():
                        await self._human_move_and_click(close_btn)
                        log(f"✓ Опрос закрито")
                        return True
                except:
                    pass
            
            try:
                close_by_text = self.page.locator('button:has-text("×")').first
                if await close_by_text.is_visible(timeout=1000):
                    await self._human_move_and_click(close_by_text)
                    log("✓ Опрос закрито через символ ×")
                    return True
            except:
                pass
            
            return False
        except:
            return False

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
                log("✓ Chrome запущено")
            except:
                self.browser = await self.playwright.chromium.launch(
                    headless=True,
                    args=browser_args
                )
                log("✓ Chromium запущено")
            
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
        """Налаштування сторінки з правильною обробкою вікон"""
        log("🔧 Налаштування сторінки...")
        
        channel = bot.get_channel(CHANNEL_ID)
        
        await self.page.goto('https://www.dtek-krem.com.ua/ua/shutdowns', wait_until='domcontentloaded', timeout=90000)
        await asyncio.sleep(5)
        
        # СПОЧАТКУ закриваємо спливаюче вікно "Шановні клієнти!"
        await self._close_attention_popup()
        await asyncio.sleep(1)
        
        # Закриваємо опрос якщо є
        await self._close_survey_if_present()
        await asyncio.sleep(1)
        
        # ТІЛЬКИ ТЕПЕР перевіряємо реальну капчу (iframe)
        has_captcha = await self._detect_captcha()
        
        if has_captcha and channel:
            log("⚠️ Виявлено капчу! Починаю інтерактивне вирішення...")
            
            self.captcha_attempts = 0
            while self.captcha_attempts < self.max_captcha_attempts:
                self.captcha_attempts += 1
                log(f"🧩 Спроба {self.captcha_attempts}/{self.max_captcha_attempts}")
                
                success = await self._handle_captcha_interactive(channel)
                
                if success:
                    break
                
                if self.captcha_attempts < self.max_captcha_attempts:
                    log("🔄 Перезавантажую сторінку для нової спроби...")
                    await self.page.reload(wait_until='domcontentloaded', timeout=30000)
                    await asyncio.sleep(3)
                    await self._close_attention_popup()
                    await self._close_survey_if_present()
            
            if self.captcha_attempts >= self.max_captcha_attempts:
                log("❌ Вичерпано всі спроби проходження капчі")
                raise Exception("Не вдалось пройти капчу після всіх спроб")
        
        # Імітуємо людяноподібну поведінку перед заповненням
        await self._random_mouse_movements()
        await self._random_delay(500, 1000)
        
        # Вводимо місто
        log("🏙 Вводжу місто...")
        city_input = self.page.locator('.discon-input-wrapper #city')
        await city_input.wait_for(state='visible', timeout=15000)
        await self._human_move_and_click(city_input)
        await city_input.clear()
        await asyncio.sleep(0.5)
        await self._human_type(city_input, 'книж')
        await asyncio.sleep(2)
        
        city_option = self.page.locator('#cityautocomplete-list > div:nth-child(2)')
        await city_option.wait_for(state='visible', timeout=15000)
        await self._human_move_and_click(city_option)
        await asyncio.sleep(2)
        
        # Вводимо вулицю
        log("🛣 Вводжу вулицю...")
        street_input = self.page.locator('.discon-input-wrapper #street')
        await street_input.wait_for(state='visible', timeout=15000)
        await self._human_move_and_click(street_input)
        await street_input.clear()
        await asyncio.sleep(0.5)
        await self._human_type(street_input, 'київ')
        await asyncio.sleep(2)
        
        street_option = self.page.locator('#streetautocomplete-list > div:nth-child(2)')
        await street_option.wait_for(state='visible', timeout=15000)
        await self._human_move_and_click(street_option)
        await asyncio.sleep(2)
        
        # Вводимо будинок
        log("🏠 Вводжу будинок...")
        house_input = self.page.locator('input#house_num')
        await house_input.wait_for(state='visible', timeout=15000)
        await self._human_move_and_click(house_input)
        await house_input.clear()
        await asyncio.sleep(0.5)
        await self._human_type(house_input, '168')
        await asyncio.sleep(2)
        
        house_option = self.page.locator('#house_numautocomplete-list > div:first-child')
        await house_option.wait_for(state='visible', timeout=15000)
        await self._human_move_and_click(house_option)
        await asyncio.sleep(3)
        
        await self._close_survey_if_present()
        
        # Отримуємо дату оновлення
        try:
            update_elem = self.page.locator('span.update')
            await update_elem.wait_for(state='visible', timeout=15000)
            self.last_update_date = await update_elem.text_content()
            self.last_update_date = self.last_update_date.strip()
            log(f"✓ Дата оновлення: {self.last_update_date}")
        except Exception as e:
            log(f"⚠ Не вдалось отримати дату: {e}")
            self.last_update_date = "Невідомо"
        
        log("✅ Сторінка налаштована!")
        await self._save_cookies()

    async def check_for_update(self):
        """Перевіряє чи змінилась дата з обробкою помилок"""
        try:
            # Закриваємо всі вікна спочатку
            await self._close_attention_popup()
            await self._close_survey_if_present()
            
            if random.random() < 0.3:
                await self._random_mouse_movements()
            
            log("🔍 Читаю дату оновлення...")
            update_elem = self.page.locator('span.update')
            
            try:
                await update_elem.wait_for(state='visible', timeout=15000)
            except asyncio.TimeoutError:
                log("⚠️ Елемент дати не з'явився - перевіряю на помилки...")
                
                # Перевіряємо чи є капча
                has_captcha = await self._detect_captcha()
                if has_captcha:
                    log("🧩 Виявлено капчу! Обробляю...")
                    channel = bot.get_channel(CHANNEL_ID)
                    if channel:
                        success = await self._handle_captcha_interactive(channel)
                        if success:
                            # Пробуємо знову після проходження капчі
                            await update_elem.wait_for(state='visible', timeout=15000)
                        else:
                            log("❌ Не вдалось пройти капчу")
                            return False
                else:
                    # Якщо капчі немає, просто перезавантажуємо
                    log("🔄 Перезавантажую сторінку...")
                    await self.page.reload(wait_until='domcontentloaded', timeout=30000)
                    await asyncio.sleep(3)
                    await self._close_attention_popup()
                    await self._close_survey_if_present()
                    await update_elem.wait_for(state='visible', timeout=15000)
            
            current_date = await update_elem.text_content()
            current_date = current_date.strip()
            
            log(f"📅 Поточна дата: {current_date}")
            log(f"📅 Остання дата: {self.last_update_date}")
            
            if current_date != self.last_update_date:
                log("🔔 ОНОВЛЕННЯ ВИЯВЛЕНО!")
                self.last_update_date = current_date
                await self._save_cookies()
                return True
            
            log("ℹ️ Дата не змінилась")
            return False
        except Exception as e:
            log(f"❌ Помилка при перевірці: {e}")
            
            # Останній шанс - перевіряємо капчу
            try:
                has_captcha = await self._detect_captcha()
                if has_captcha:
                    log("🧩 Виявлено капчу після помилки!")
                    channel = bot.get_channel(CHANNEL_ID)
                    if channel:
                        await self._handle_captcha_interactive(channel)
            except:
                pass
            
            return False

    async def parse_schedule(self):
        """Парсить графік відключень з активної вкладки"""
        try:
            date_elem = self.page.locator('.date.active')
            schedule_date = await date_elem.text_content()
            schedule_date = schedule_date.strip() if schedule_date else "Невідомо"
            
            result = {
                'date': schedule_date,
                'hours': [],
                'schedule': {}
            }
            
            for i in range(2, 26):
                try:
                    hour_selector = f'.active > table th:nth-child({i})'
                    hour_elem = self.page.locator(hour_selector)
                    hour_text = await hour_elem.text_content()
                    hour_text = hour_text.strip()
                    result['hours'].append(hour_text)
                except:
                    result['hours'].append(f"??:??")
            
            for i in range(2, 26):
                try:
                    cell_selector = f'.active > table td:nth-child({i})'
                    cell_elem = self.page.locator(cell_selector)
                    cell_class = await cell_elem.get_attribute('class')
                    cell_class = cell_class.strip() if cell_class else ""
                    
                    hour = result['hours'][i-2]
                    
                    if 'cell-scheduled' in cell_class:
                        status = 'scheduled'
                    elif 'cell-non-scheduled' in cell_class:
                        status = 'powered'
                    elif 'cell-first-half' in cell_class:
                        status = 'first-half'
                    elif 'cell-second-half' in cell_class:
                        status = 'second-half'
                    else:
                        status = 'powered'
                    
                    result['schedule'][hour] = {
                        'status': status,
                        'class': cell_class
                    }
                    
                except Exception as e:
                    hour = result['hours'][i-2] if i-2 < len(result['hours']) else "??:??"
                    result['schedule'][hour] = {
                        'status': 'error',
                        'class': ''
                    }
            
            return result
            
        except Exception as e:
            log(f"❌ Помилка парсингу: {e}")
            return None

    def _calculate_schedule_hash(self, schedule):
        """Розраховує хеш графіка для порівняння"""
        if not schedule:
            return None
        
        status_string = ""
        for hour in sorted(schedule['schedule'].keys()):
            status_string += f"{hour}:{schedule['schedule'][hour]['status']};"
        
        return hashlib.md5(status_string.encode()).hexdigest()

    def _has_any_outages(self, schedule):
        """Перевіряє чи є хоч одне відключення в графіку"""
        if not schedule or not schedule.get('schedule'):
            return False
        
        for hour_data in schedule['schedule'].values():
            status = hour_data.get('status')
            if status in ['scheduled', 'first-half', 'second-half']:
                return True
        
        return False

    def _count_outage_hours(self, schedule):
        """Підраховує кількість годин з відключенням"""
        if not schedule or not schedule.get('schedule'):
            return 0
        
        count = 0
        for hour_data in schedule['schedule'].values():
            status = hour_data.get('status')
            if status in ['scheduled', 'first-half', 'second-half']:
                count += 1
        
        return count

    def _merge_consecutive_hours(self, hours_list):
        """Об'єднує суміжні години в діапазони (наприклад: ['03-04', '04-05', '05-06'] -> '03-07')"""
        if not hours_list:
            return []
        
        # Сортуємо години
        hours_list = sorted(hours_list)
        
        merged = []
        current_start = None
        current_end = None
        
        for hour_range in hours_list:
            # Парсимо діапазон (наприклад "03-04")
            try:
                start, end = hour_range.split('-')
                start_num = int(start.split(':')[0])
                end_num = int(end.split(':')[0])
                
                if current_start is None:
                    # Перший діапазон
                    current_start = start
                    current_end = end
                    current_end_num = end_num
                elif start_num == current_end_num:
                    # Суміжний діапазон - продовжуємо
                    current_end = end
                    current_end_num = end_num
                else:
                    # Розрив - зберігаємо попередній і починаємо новий
                    if current_start == current_end.split(':')[0]:
                        merged.append(current_start)
                    else:
                        merged.append(f"{current_start}-{current_end}")
                    current_start = start
                    current_end = end
                    current_end_num = end_num
            except:
                # Якщо не вдалось розпарсити - додаємо як є
                if current_start:
                    if current_start == current_end.split(':')[0]:
                        merged.append(current_start)
                    else:
                        merged.append(f"{current_start}-{current_end}")
                merged.append(hour_range)
                current_start = None
                current_end = None
        
        # Додаємо останній діапазон
        if current_start:
            # Перевіряємо чи початок і кінець однакові
            start_hour = current_start.split(':')[0]
            end_hour = current_end.split(':')[0]
            if start_hour == end_hour:
                merged.append(start_hour)
            else:
                merged.append(f"{start_hour}-{end_hour}")
        
        return merged

    def _compare_schedules(self, old_schedule, new_schedule):
        """Порівнює два графіки і повертає текстовий опис змін"""
        log("🔍 === ПОЧАТОК ПОРІВНЯННЯ ГРАФІКІВ ===")
        
        log(f"🔍 Тип old_schedule: {type(old_schedule)}")
        log(f"🔍 Тип new_schedule: {type(new_schedule)}")
        
        if isinstance(old_schedule, str):
            log("⚠️ old_schedule є рядком, парсимо JSON...")
            try:
                old_schedule = json.loads(old_schedule)
                log("✓ JSON успішно розпарсено")
            except Exception as e:
                log(f"❌ Помилка парсингу JSON: {e}")
                return "📊 Помилка парсингу старого графіка"
        
        if isinstance(new_schedule, str):
            log("⚠️ new_schedule є рядком, парсимо JSON...")
            try:
                new_schedule = json.loads(new_schedule)
                log("✓ JSON успішно розпарсено")
            except Exception as e:
                log(f"❌ Помилка парсингу JSON: {e}")
                return "📊 Помилка парсингу нового графіка"
        
        if not old_schedule or not new_schedule:
            log("⚠️ Один з графіків порожній")
            return "📊 Перша перевірка - немає з чим порівнювати"
        
        if 'schedule' not in old_schedule:
            log(f"❌ 'schedule' відсутній в old_schedule. Ключі: {old_schedule.keys()}")
            return "📊 Некоректний формат старого графіка"
        
        if 'schedule' not in new_schedule:
            log(f"❌ 'schedule' відсутній в new_schedule. Ключі: {new_schedule.keys()}")
            return "📊 Некоректний формат нового графіка"
        
        log(f"✓ Кількість годин в старому графіку: {len(old_schedule['schedule'])}")
        log(f"✓ Кількість годин в новому графіку: {len(new_schedule['schedule'])}")
        
        # Підраховуємо години з відключеннями
        old_outage_count = self._count_outage_hours(old_schedule)
        new_outage_count = self._count_outage_hours(new_schedule)
        
        log(f"📊 Старий графік: {old_outage_count} годин без світла")
        log(f"📊 Новий графік: {new_outage_count} годин без світла")
        
        added_outages = []
        removed_outages = []
        
        for hour in new_schedule['schedule'].keys():
            old_status = old_schedule['schedule'].get(hour, {}).get('status', 'unknown')
            new_status = new_schedule['schedule'][hour]['status']
            
            if old_status != new_status:
                log(f"🔄 Зміна в {hour}: {old_status} → {new_status}")
            
            if old_status in ['powered'] and new_status in ['scheduled', 'first-half', 'second-half']:
                added_outages.append(hour)
                log(f"⚡ {hour}: З'явилось відключення")
            elif old_status in ['scheduled', 'first-half', 'second-half'] and new_status in ['powered']:
                removed_outages.append(hour)
                log(f"✅ {hour}: З'явилось світло")
        
        log(f"📊 Підсумок: додано відключень: {len(added_outages)}, прибрано: {len(removed_outages)}")
        
        # Формуємо підсумковий текст
        if not added_outages and not removed_outages:
            log("ℹ️ Графік не змінився")
            return None
        
        # Об'єднуємо суміжні години
        added_outages_merged = self._merge_consecutive_hours(added_outages)
        removed_outages_merged = self._merge_consecutive_hours(removed_outages)
        
        log(f"📊 Об'єднані відключення додано: {added_outages_merged}")
        log(f"📊 Об'єднані відключення прибрано: {removed_outages_merged}")
        
        # Перевіряємо чи просто переставили
        if len(added_outages) == len(removed_outages) and len(added_outages) > 0:
            result = f"🔄 **Переставили відключення**\n"
            result += f"⚡ Тепер відключення: {', '.join(added_outages_merged)}\n"
            result += f"✅ Тепер світло: {', '.join(removed_outages_merged)}"
            log(f"✓ Результат: Переставили відключення")
        else:
            result_parts = []
            
            if new_outage_count > old_outage_count:
                diff = new_outage_count - old_outage_count
                result_parts.append(f"⚡ **Годин без світла: +{diff}**")
                if added_outages_merged:
                    result_parts.append(f"Додалось відключення: {', '.join(added_outages_merged)}")
            elif new_outage_count < old_outage_count:
                diff = old_outage_count - new_outage_count
                result_parts.append(f"✅ **Годин зі світлом: +{diff}**")
                if removed_outages_merged:
                    result_parts.append(f"З'явилось світло: {', '.join(removed_outages_merged)}")
            else:
                if added_outages_merged:
                    result_parts.append(f"⚡ Додалось відключення: {', '.join(added_outages_merged)}")
                if removed_outages_merged:
                    result_parts.append(f"✅ З'явилось світло: {', '.join(removed_outages_merged)}")
            
            result = "\n".join(result_parts)
        
        log(f"✓ Результат порівняння: {result}")
        log("🔍 === КІНЕЦЬ ПОРІВНЯННЯ ГРАФІКІВ ===")
        
        return result

    def crop_screenshot(self, screenshot_bytes, top_crop=300, bottom_crop=400, left_crop=0, right_crop=0):
        """Обрізає скріншот"""
        try:
            image = Image.open(io.BytesIO(screenshot_bytes))
            width, height = image.size
            
            left = left_crop
            top = top_crop
            right = width - right_crop
            bottom = height - bottom_crop
            
            log(f"✂️ Обрізаю скріншот: {width}x{height} -> {right-left}x{bottom-top}")
            log(f"   Координати: left={left}, top={top}, right={right}, bottom={bottom}")
            
            cropped = image.crop((left, top, right, bottom))
            
            output = io.BytesIO()
            cropped.save(output, format='PNG', optimize=True, quality=95)
            return output.getvalue()
        except Exception as e:
            log(f"⚠ Помилка при обрізці скріншота: {e}")
            return screenshot_bytes

    async def _make_screenshot_with_retry(self, max_attempts=2):
        """Робить скріншот з повторними спробами"""
        for attempt in range(1, max_attempts + 1):
            try:
                log(f"📸 Спроба {attempt}/{max_attempts} зробити скріншот...")
                screenshot = await asyncio.wait_for(
                    self.page.screenshot(full_page=True, type='png'),
                    timeout=60
                )
                log(f"✓ Скріншот отримано ({len(screenshot)} байт)")
                return screenshot
            except asyncio.TimeoutError:
                log(f"⏱️ Таймаут на спробі {attempt}/{max_attempts}")
                if attempt < max_attempts:
                    log("🔄 Пробую ще раз через 3 секунди...")
                    await asyncio.sleep(3)
                    try:
                        await self.page.reload(wait_until='domcontentloaded', timeout=30000)
                        await asyncio.sleep(2)
                        log("✓ Сторінка оновлена")
                    except:
                        log("⚠️ Не вдалось оновити сторінку")
                else:
                    log(f"❌ Всі {max_attempts} спроби вичерпано")
                    raise
            except Exception as e:
                log(f"❌ Помилка при створенні скріншота: {e}")
                if attempt < max_attempts:
                    log("🔄 Пробую ще раз...")
                    await asyncio.sleep(3)
                else:
                    raise
        
        raise Exception(f"Не вдалось зробити скріншот за {max_attempts} спроб")

    async def make_screenshots(self):
        """Робить скріншоти з парсингом графіка"""
        try:
            log("🔍 Перевіряю наявність вікон...")
            await self._close_attention_popup()
            await self._close_survey_if_present()
            await asyncio.sleep(0.5)
            
            # СЬОГОДНІ
            log("")
            log("="*50)
            log("📊 ПАРСИНГ ГРАФІКА НА СЬОГОДНІ")
            log("="*50)
            
            log("📋 Парсю графік на сьогодні...")
            schedule_today = await self.parse_schedule()
            if schedule_today:
                log(f"✓ Графік розпарсено: {len(schedule_today.get('schedule', {}))} годин")
            else:
                log("❌ Не вдалось розпарсити графік")
            
            log("🔍 Перевіряю що таблиця графіка видима...")
            try:
                table = self.page.locator('.active > table')
                await table.wait_for(state='visible', timeout=10000)
                log("✓ Таблиця графіка видима")
            except Exception as e:
                log(f"⚠️ Таблиця не знайдена: {e}")
            
            log("📸 Роблю скріншот основного графіка...")
            try:
                screenshot_main = await self._make_screenshot_with_retry(max_attempts=2)
            except Exception as e:
                log(f"❌ Критична помилка при створенні скріншота: {e}")
                raise
            
            # Обрізаємо за точними координатами
            screenshot_main_cropped = self.crop_screenshot(screenshot_main, top_crop=300, bottom_crop=1579, left_crop=775, right_crop=315)
            log(f"✓ Скріншот обрізано ({len(screenshot_main_cropped)} байт)")
            
            # ЗАВТРА
            log("")
            log("="*50)
            log("📊 ПАРСИНГ ГРАФІКА НА ЗАВТРА")
            log("="*50)
            
            second_date = None
            screenshot_tomorrow_cropped = None
            schedule_tomorrow = None
            
            try:
                log("🔍 Шукаю другий графік...")
                date_selector = self.page.locator('div.date:nth-child(2)')
                await date_selector.wait_for(state='visible', timeout=15000)
                
                second_date = await date_selector.text_content()
                second_date = second_date.strip()
                log(f"📅 Дата другого графіка: {second_date}")
                
                log("🖱️ Клікаю на другий графік...")
                await self._human_move_and_click(date_selector)
                log("⏳ Чекаю завантаження (2 сек)...")
                await asyncio.sleep(2)
                
                log("🔍 Перевіряю опрос після перемикання...")
                await self._close_survey_if_present()
                
                log("📋 Парсю графік на завтра...")
                schedule_tomorrow = await self.parse_schedule()
                if schedule_tomorrow:
                    log(f"✓ Графік розпарсено: {len(schedule_tomorrow.get('schedule', {}))} годин")
                
                log("📸 Роблю скріншот другого графіка...")
                try:
                    screenshot_tomorrow = await self._make_screenshot_with_retry(max_attempts=2)
                except asyncio.TimeoutError:
                    log("❌ Таймаут при створенні скріншота завтра після всіх спроб")
                    screenshot_tomorrow = None
                except Exception as e:
                    log(f"❌ Помилка скріншота завтра: {e}")
                    screenshot_tomorrow = None
                
                if screenshot_tomorrow:
                    screenshot_tomorrow_cropped = self.crop_screenshot(screenshot_tomorrow, top_crop=300, bottom_crop=1579, left_crop=775, right_crop=315)
                    log(f"✓ Скріншот обрізано ({len(screenshot_tomorrow_cropped)} байт)")
                
                log("🔙 Повертаюсь на перший графік...")
                first_date = self.page.locator('div.date:nth-child(1)')
                await first_date.wait_for(state='visible', timeout=10000)
                await self._human_move_and_click(first_date)
                await asyncio.sleep(2)
                log(f"✓ Повернувся на перший графік")
                
            except asyncio.TimeoutError:
                log(f"⚠ Таймаут при роботі зі другим графіком")
            except Exception as e:
                log(f"⚠ Не вдалось отримати другий графік: {e}")
            
            log("")
            log("="*50)
            log("✅ СКРІНШОТИ ГОТОВІ")
            log("="*50)
            
            return {
                'screenshot_main': screenshot_main_cropped,
                'screenshot_tomorrow': screenshot_tomorrow_cropped,
                'update_date': self.last_update_date,
                'second_date': second_date,
                'schedule_today': schedule_today,
                'schedule_tomorrow': schedule_tomorrow,
                'timestamp': datetime.now(UKRAINE_TZ).isoformat()
            }
            
        except Exception as e:
            log(f"✖️ Помилка при створенні скріншотів: {e}")
            import traceback
            log(f"Stack trace: {traceback.format_exc()}")
            raise

    async def close_browser(self):
        """Закриття браузера"""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None
        log("✓ Браузер закрито")
    
    async def restart_browser(self):
        """Повний перезапуск браузера"""
        log("🔄 Починаю перезапуск браузера...")
        try:
            # Зберігаємо останню дату перед перезапуском
            old_date = self.last_update_date
            
            await self._save_cookies()
            await self.close_browser()
            await asyncio.sleep(3)
            
            # Ініціалізуємо заново - це включає заповнення форми
            await self.init_browser()
            
            log("✅ Браузер успішно перезапущено!")
            log(f"📅 Дата до перезапуску: {old_date}")
            log(f"📅 Дата після перезапуску: {self.last_update_date}")
            
            return True
        except Exception as e:
            log(f"❌ Помилка при перезапуску браузера: {e}")
            import traceback
            log(f"Stack trace: {traceback.format_exc()}")
            return False

checker = DTEKChecker()

async def get_last_check():
    """Отримує дані останньої перевірки з БД"""
    try:
        log("📂 Читаю останню перевірку з БД...")
        async with db_pool.acquire() as conn:
            # Спочатку перевіряємо які колонки існують
            columns_check = await conn.fetch("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'dtek_checks'
            """)
            existing_columns = [row['column_name'] for row in columns_check]
            log(f"🔍 Наявні колонки в БД: {existing_columns}")
            
            has_tomorrow_cols = 'schedule_tomorrow_hash' in existing_columns and 'schedule_tomorrow_data' in existing_columns
            
            # Формуємо запит залежно від наявності колонок
            if has_tomorrow_cols:
                query = '''
                    SELECT update_date, schedule_hash, schedule_data, 
                           schedule_tomorrow_hash, schedule_tomorrow_data, created_at 
                    FROM dtek_checks 
                    ORDER BY created_at DESC LIMIT 1
                '''
            else:
                query = '''
                    SELECT update_date, schedule_hash, schedule_data, created_at 
                    FROM dtek_checks 
                    ORDER BY created_at DESC LIMIT 1
                '''
                log("⚠️ Стара структура БД (без колонок для графіка завтра)")
            
            row = await conn.fetchrow(query)
            
            if row:
                log(f"✓ Знайдено запис від {row['created_at']}")
                
                schedule_data = row['schedule_data']
                log(f"🔍 Тип даних з БД: schedule_data={type(schedule_data)}")
                
                if isinstance(schedule_data, str):
                    log("⚠️ schedule_data є рядком, парсимо JSON...")
                    try:
                        schedule_data = json.loads(schedule_data)
                        log(f"✓ JSON розпарсено")
                    except Exception as e:
                        log(f"❌ Помилка парсингу JSON: {e}")
                        return None
                
                result = {
                    'update_date': row['update_date'],
                    'schedule_hash': row['schedule_hash'],
                    'schedule_data': schedule_data,
                    'schedule_tomorrow_hash': None,
                    'schedule_tomorrow_data': None,
                    'created_at': row['created_at']
                }
                
                # Додаємо дані завтра якщо є
                if has_tomorrow_cols and row.get('schedule_tomorrow_data'):
                    schedule_tomorrow_data = row['schedule_tomorrow_data']
                    if isinstance(schedule_tomorrow_data, str):
                        log("⚠️ schedule_tomorrow_data є рядком, парсимо JSON...")
                        try:
                            schedule_tomorrow_data = json.loads(schedule_tomorrow_data)
                            log(f"✓ JSON розпарсено")
                        except Exception as e:
                            log(f"❌ Помилка парсингу JSON: {e}")
                            schedule_tomorrow_data = None
                    
                    result['schedule_tomorrow_hash'] = row.get('schedule_tomorrow_hash')
                    result['schedule_tomorrow_data'] = schedule_tomorrow_data
                
                log(f"✓ Повертаю дані: update_date={result['update_date']}, has_tomorrow={result['schedule_tomorrow_hash'] is not None}")
                return result
            else:
                log("ℹ️ Записів в БД не знайдено")
                return None
    except Exception as e:
        log(f"❌ Помилка при отриманні даних з БД: {e}")
        import traceback
        log(f"Stack trace: {traceback.format_exc()}")
    return None

async def save_check(update_date, schedule_hash, schedule_data, schedule_tomorrow_hash=None, schedule_tomorrow_data=None):
    """Зберігає дані перевірки в БД"""
    try:
        log(f"💾 Зберігаю в БД:")
        log(f"  📅 update_date: {update_date}")
        log(f"  🔐 schedule_hash: {schedule_hash}")
        log(f"  🔐 schedule_tomorrow_hash: {schedule_tomorrow_hash}")
        log(f"  🔍 Тип schedule_data: {type(schedule_data)}")
        
        async with db_pool.acquire() as conn:
            # Перевіряємо які колонки існують
            columns_check = await conn.fetch("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'dtek_checks'
            """)
            existing_columns = [row['column_name'] for row in columns_check]
            has_tomorrow_cols = 'schedule_tomorrow_hash' in existing_columns and 'schedule_tomorrow_data' in existing_columns
            
            schedule_json = json.dumps(schedule_data)
            log(f"  📦 Розмір JSON сьогодні: {len(schedule_json)} символів")
            
            # Використовуємо UTC datetime без timezone (naive) для сумісності з PostgreSQL
            now_utc = datetime.now(UKRAINE_TZ).astimezone(pytz.UTC).replace(tzinfo=None)
            
            if has_tomorrow_cols and schedule_tomorrow_data:
                # Нова структура БД - зберігаємо все
                schedule_tomorrow_json = json.dumps(schedule_tomorrow_data)
                log(f"  📦 Розмір JSON завтра: {len(schedule_tomorrow_json)} символів")
                
                await conn.execute(
                    '''INSERT INTO dtek_checks 
                       (update_date, schedule_hash, schedule_data, schedule_tomorrow_hash, schedule_tomorrow_data, created_at) 
                       VALUES ($1, $2, $3, $4, $5, $6)''',
                    update_date, schedule_hash, schedule_json, schedule_tomorrow_hash, schedule_tomorrow_json, now_utc
                )
                log(f"✓ Дані успішно збережено в БД (з графіком завтра)")
            else:
                # Стара структура БД - зберігаємо тільки сьогодні
                await conn.execute(
                    '''INSERT INTO dtek_checks 
                       (update_date, schedule_hash, schedule_data, created_at) 
                       VALUES ($1, $2, $3, $4)''',
                    update_date, schedule_hash, schedule_json, now_utc
                )
                log(f"✓ Дані успішно збережено в БД (без графіка завтра - стара структура)")
                
    except Exception as e:
        log(f"✖️ Помилка при збереженні в БД: {e}")
        import traceback
        log(f"Stack trace: {traceback.format_exc()}")

@bot.event
async def on_ready():
    log(f'✓ {bot.user} підключено до Discord!')
    log(f'✓ Моніторинг каналу: {CHANNEL_ID}')
    log(f'✓ Інтервал перевірки: кожні 5 хвилин')
    log(f'🌐 Веб-інтерфейс запущено на порту {PORT}')
    log(f'🥷 STEALTH MODE активовано')
    log(f'🕐 Часовий пояс: Europe/Kiev (UTC+2/+3)')
    
    await init_db_pool()
    await start_web_server()
    
    log("")
    log("="*60)
    log("💡 ВАЖЛИВО: Браузер ще не ініціалізовано!")
    log(f"🌐 Відкрийте веб-інтерфейс: http://localhost:{PORT}")
    log("🖱️ Натисніть кнопку 'Ініціалізувати браузер'")
    log("="*60)
    log("")
    
    log("🎉 Бот готовий до роботи!")
    now = datetime.now(UKRAINE_TZ)
    log(f"⏰ Поточний час: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
    check_schedule.start()
    log("✓ Автоматична перевірка запущена (кожні 5 хвилин)")
    
    restart_browser_task.start()
    log("✓ Автоматичний перезапуск браузера запущено (щодня о 23:58)")
    log("")

@tasks.loop(minutes=5)
async def check_schedule():
    """Періодична перевірка кожні 5 хвилин"""
    channel = None
    try:
        log("")
        log("="*50)
        log(f"⏰ Час для автоматичної перевірки")
        log("="*50)
        
        if not checker.browser or not checker.page:
            log("⏸️ Браузер не ініціалізовано, пропускаю перевірку")
            log("💡 Відкрийте веб-інтерфейс та натисніть 'Ініціалізувати браузер'")
            log(f"⏰ Наступна перевірка о: {(datetime.now() + timedelta(minutes=5)).strftime('%H:%M:%S')}")
            log("="*50)
            log("")
            return
        
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            log(f"✖️ Канал {CHANNEL_ID} не знайдено!")
            return
        
        log("🔍 Починаю перевірку оновлень...")
        
        has_update = await checker.check_for_update()
        
        if not has_update:
            log(f"ℹ️ Без змін (дата не оновилась)")
            next_check = datetime.now(UKRAINE_TZ) + timedelta(minutes=5)
            log(f"⏰ Наступна перевірка о: {next_check.strftime('%H:%M:%S')}")
            log("="*50)
            log("")
            return
        
        # Дата оновилась - робимо скріншоти і парсимо
        log("📸 Дата оновилась! Роблю скріншоти...")
        try:
            result = await asyncio.wait_for(checker.make_screenshots(), timeout=240)
            log("✅ Скріншоти успішно створено")
        except asyncio.TimeoutError:
            log("❌ Таймаут створення скріншотів (4 хвилини)")
            raise
        
        # Отримуємо останню перевірку з БД
        schedule_today = result.get('schedule_today')
        schedule_tomorrow = result.get('schedule_tomorrow')
        
        log(f"🔍 Отримано графік на сьогодні: {type(schedule_today)}")
        if schedule_tomorrow:
            log(f"🔍 Отримано графік на завтра: {type(schedule_tomorrow)}")
        
        if not schedule_today:
            log("❌ Не вдалось отримати графік на сьогодні")
            return
        
        current_hash = checker._calculate_schedule_hash(schedule_today)
        current_tomorrow_hash = checker._calculate_schedule_hash(schedule_tomorrow) if schedule_tomorrow else None
        
        log(f"🔐 Хеш поточного графіка (сьогодні): {current_hash}")
        if current_tomorrow_hash:
            log(f"🔐 Хеш поточного графіка (завтра): {current_tomorrow_hash}")
        
        last_check = await get_last_check()
        
        # Визначаємо які графіки змінились
        today_changed = True
        tomorrow_changed = True
        
        if last_check:
            log(f"📂 Знайдено попередню перевірку з БД")
            log(f"🔐 Хеш попереднього графіка (сьогодні): {last_check['schedule_hash']}")
            if last_check.get('schedule_tomorrow_hash'):
                log(f"🔐 Хеш попереднього графіка (завтра): {last_check.get('schedule_tomorrow_hash')}")
            
            # Перевіряємо чи змінився графік СЬОГОДНІ
            if last_check['schedule_hash'] == current_hash:
                log("⏸️ Графік СЬОГОДНІ не змінився")
                today_changed = False
            else:
                log("🔔 Графік СЬОГОДНІ змінився!")
                today_changed = True
            
            # Перевіряємо чи змінився графік ЗАВТРА
            if current_tomorrow_hash:
                if last_check.get('schedule_tomorrow_hash'):
                    if last_check['schedule_tomorrow_hash'] == current_tomorrow_hash:
                        log("⏸️ Графік ЗАВТРА не змінився")
                        tomorrow_changed = False
                    else:
                        log("🔔 Графік ЗАВТРА змінився!")
                        tomorrow_changed = True
                else:
                    # Попереднього графіка завтра немає - вважаємо що змінився
                    log("ℹ️ Попереднього графіка ЗАВТРА немає в БД - вважаємо що змінився")
                    tomorrow_changed = True
            else:
                log("ℹ️ Графік ЗАВТРА відсутній")
                tomorrow_changed = False
        else:
            log("📊 Попередня перевірка не знайдена (перший запуск)")
            # При першому запуску відправляємо обидва
            today_changed = True
            tomorrow_changed = True if current_tomorrow_hash else False
        
        # Якщо жоден графік не змінився - не відправляємо нічого
        if not today_changed and not tomorrow_changed:
            log("⏸️ Жоден з графіків не змінився - не відправляю повідомлення")
            next_check = datetime.now(UKRAINE_TZ) + timedelta(minutes=5)
            log(f"⏰ Наступна перевірка о: {next_check.strftime('%H:%M:%S')}")
            log("="*50)
            log("")
            return
        
        # Зберігаємо в БД нові дані
        await save_check(result['update_date'], current_hash, schedule_today, current_tomorrow_hash, schedule_tomorrow)
        
        # Для Discord embeds використовуємо naive UTC datetime
        timestamp_now = datetime.now(UKRAINE_TZ).astimezone(pytz.UTC).replace(tzinfo=None)
        timestamp_str = datetime.now(UKRAINE_TZ).strftime('%Y%m%d_%H%M%S')
        
        # Відправляємо СЬОГОДНІ якщо змінився
        if today_changed:
            log("📤 Відправляю графік СЬОГОДНІ...")
            
            # Порівнюємо з попереднім
            changes_text = None
            if last_check and last_check.get('schedule_data'):
                log("🔄 Починаю порівняння графіків (СЬОГОДНІ)...")
                old_schedule = last_check['schedule_data']
                if isinstance(old_schedule, str):
                    log("⚠️ schedule_data є рядком, конвертую...")
                    try:
                        old_schedule = json.loads(old_schedule)
                    except Exception as e:
                        log(f"❌ Помилка конвертації: {e}")
                        old_schedule = None
                
                if old_schedule:
                    try:
                        changes_text = checker._compare_schedules(old_schedule, schedule_today)
                        log(f"✓ Порівняння завершено")
                    except Exception as e:
                        log(f"❌ Помилка при порівнянні: {e}")
                        import traceback
                        log(f"Stack trace: {traceback.format_exc()}")
                        changes_text = None
            
            # Формуємо дату для заголовка
            update_date_display = result['update_date'] if result.get('update_date') else 'сьогодні'
            
            embed = discord.Embed(
                title=f"📊 Графік оновився {update_date_display}",
                color=discord.Color.gold(),
                timestamp=timestamp_now
            )
            
            if result['update_date']:
                embed.add_field(
                    name="📅 Дата оновлення на сайті",
                    value=f"`{result['update_date']}`",
                    inline=False
                )
            
            if changes_text:
                embed.add_field(
                    name="📊 Що змінилось:",
                    value=changes_text,
                    inline=False
                )
            
            embed.set_footer(text="Автоматична перевірка")
            
            file_main = discord.File(
                io.BytesIO(result['screenshot_main']), 
                filename=f"dtek_today_{timestamp_str}.png"
            )
            
            await channel.send(embed=embed, file=file_main)
            log("✓ Графік СЬОГОДНІ відправлено")
        else:
            log("⏸️ Графік СЬОГОДНІ не змінився - пропускаю")
        
        # Відправляємо ЗАВТРА якщо змінився Є Є відключення
        if tomorrow_changed and schedule_tomorrow and result.get('screenshot_tomorrow'):
            has_outages = checker._has_any_outages(schedule_tomorrow)
            
            if has_outages:
                log("📤 Відправляю графік ЗАВТРА...")
                
                # Порівнюємо з попереднім
                changes_text_tomorrow = None
                if last_check and last_check.get('schedule_tomorrow_data'):
                    log("🔄 Починаю порівняння графіків (ЗАВТРА)...")
                    old_schedule_tomorrow = last_check['schedule_tomorrow_data']
                    if isinstance(old_schedule_tomorrow, str):
                        try:
                            old_schedule_tomorrow = json.loads(old_schedule_tomorrow)
                        except:
                            old_schedule_tomorrow = None
                    
                    if old_schedule_tomorrow:
                        try:
                            changes_text_tomorrow = checker._compare_schedules(old_schedule_tomorrow, schedule_tomorrow)
                        except Exception as e:
                            log(f"❌ Помилка порівняння (ЗАВТРА): {e}")
                            changes_text_tomorrow = None
                
                # Формуємо дату для заголовка
                tomorrow_date_display = result['second_date'] if result.get('second_date') else 'завтра'
                
                embed_tomorrow = discord.Embed(
                    title=f"📅 Графік оновився {tomorrow_date_display}",
                    color=discord.Color.blue(),
                    timestamp=timestamp_now
                )
                
                if changes_text_tomorrow:
                    embed_tomorrow.add_field(
                        name="📊 Що змінилось:",
                        value=changes_text_tomorrow,
                        inline=False
                    )
                
                embed_tomorrow.set_footer(text="Автоматична перевірка")
                
                file_tomorrow = discord.File(
                    io.BytesIO(result['screenshot_tomorrow']), 
                    filename=f"dtek_tomorrow_{timestamp_str}.png"
                )
                
                await channel.send(embed=embed_tomorrow, file=file_tomorrow)
                log("✓ Графік ЗАВТРА відправлено")
            else:
                log("⏸️ Завтра немає відключень - не відправляю")
        elif not tomorrow_changed:
            log("⏸️ Графік ЗАВТРА не змінився - пропускаю")
        
        log(f"✓ Перевірка завершена")
        next_check = datetime.now(UKRAINE_TZ) + timedelta(minutes=5)
        log(f"⏰ Наступна перевірка о: {next_check.strftime('%H:%M:%S')}")
        log("="*50)
        log("")
        
    except asyncio.TimeoutError:
        log(f"⏱️ ТАЙМАУТ: Операція зайняла більше 4 хвилин")
        next_check = datetime.now(UKRAINE_TZ) + timedelta(minutes=5)
        log(f"⏰ Наступна перевірка о: {next_check.strftime('%H:%M:%S')}")
        log("="*50)
        log("")
        if channel:
            try:
                error_embed = discord.Embed(
                    title="⏱️ Таймаут операції",
                    description="Перевірка зайняла більше 4 хвилин. Можливо, сайт повільно завантажується або виникла проблема з мережею.",
                    color=discord.Color.dark_gray(),
                    timestamp=datetime.utcnow()
                )
                await channel.send(embed=error_embed)
            except:
                pass
    except Exception as e:
        log(f"✖️ Помилка в check_schedule: {e}")
        next_check = datetime.now(UKRAINE_TZ) + timedelta(minutes=5)
        log(f"⏰ Наступна перевірка о: {next_check.strftime('%H:%M:%S')}")
        
        if channel:
            try:
                error_embed = discord.Embed(
                    title="⚠️ Помилка перевірки",
                    description=f"Не вдалось виконати перевірку.\n```{str(e)[:200]}```",
                    color=discord.Color.dark_gray(),
                    timestamp=datetime.utcnow()
                )
                await channel.send(embed=error_embed)
            except:
                pass

@check_schedule.before_loop
async def before_check_schedule():
    """Чекаємо, поки бот буде готовий"""
    await bot.wait_until_ready()
    log("⏳ Очікування готовності бота завершено")
    
    if checker.browser and checker.page:
        log("🔥 Прогрів сторінки перед першою перевіркою...")
        try:
            await checker.page.reload(wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(3)
            await checker._close_attention_popup()
            await checker._close_survey_if_present()
            log("✓ Сторінка прогріта")
        except Exception as e:
            log(f"⚠️ Не вдалось прогріти сторінку: {e}")
    
    log("✓ Автоматичні перевірки почнуться через 5 хвилин")
    next_check = datetime.now(UKRAINE_TZ) + timedelta(minutes=5)
    log(f"⏰ Наступна перевірка о: {next_check.strftime('%H:%M:%S')}")

@tasks.loop(minutes=1)
async def restart_browser_task():
    """Перевіряє чи потрібно перезапустити браузер о 23:58"""
    try:
        now = datetime.now(UKRAINE_TZ)
        current_time = now.strftime('%H:%M')
        
        # Перезапуск о 23:58
        if current_time == '23:58':
            log("")
            log("="*60)
            log("🔄 ЧАС ДЛЯ ПЕРЕЗАПУСКУ БРАУЗЕРА (23:58)")
            log("="*60)
            
            if checker.browser and checker.page:
                channel = bot.get_channel(CHANNEL_ID)
                if channel:
                    try:
                        info_embed = discord.Embed(
                            title="🔄 Технічне обслуговування",
                            description="Перезапускаю браузер для оновлення дати на сайті.\nПоверну через хвилину!",
                            color=discord.Color.blue(),
                            timestamp=datetime.utcnow()
                        )
                        await channel.send(embed=info_embed)
                    except:
                        pass
                
                success = await checker.restart_browser()
                
                if success:
                    log("✅ Браузер перезапущено успішно!")
                    if channel:
                        try:
                            success_embed = discord.Embed(
                                title="✅ Обслуговування завершено",
                                description="Браузер перезапущено. Продовжую моніторинг!",
                                color=discord.Color.green(),
                                timestamp=datetime.utcnow()
                            )
                            await channel.send(embed=success_embed)
                        except:
                            pass
                else:
                    log("❌ Не вдалось перезапустити браузер!")
                    if channel:
                        try:
                            error_embed = discord.Embed(
                                title="⚠️ Помилка перезапуску",
                                description="Не вдалось перезапустити браузер. Потрібна ручна ініціалізація через веб-інтерфейс.",
                                color=discord.Color.red(),
                                timestamp=datetime.utcnow()
                            )
                            await channel.send(embed=error_embed)
                        except:
                            pass
                
                log("="*60)
                log("")
                
                # Чекаємо 2 хвилини щоб не запускати знову
                await asyncio.sleep(120)
            else:
                log("⏸️ Браузер не запущено - пропускаю перезапуск")
                
    except Exception as e:
        log(f"❌ Помилка в restart_browser_task: {e}")

@restart_browser_task.before_loop
async def before_restart_browser_task():
    """Чекаємо готовності бота"""
    await bot.wait_until_ready()
    log("✓ Задача перезапуску браузера готова")

@bot.command(name='check')
async def manual_check(ctx):
    """Ручна перевірка по команді !check"""
    if not checker.browser or not checker.page:
        await ctx.send("✖️ Браузер не ініціалізовано. Відкрийте веб-інтерфейс та натисніть 'Ініціалізувати браузер'")
        return
    
    await ctx.send("⏳ Починаю перевірку графіка відключень...")
    
    try:
        log("🎮 [MANUAL] Ручна перевірка запущена")
        result = await asyncio.wait_for(checker.make_screenshots(), timeout=240)
        log("✅ [MANUAL] Скріншоти створено")
        
        schedule_today = result.get('schedule_today')
        schedule_tomorrow = result.get('schedule_tomorrow')
        
        log(f"🔍 [MANUAL] Отримано графік: {type(schedule_today)}")
        current_hash = checker._calculate_schedule_hash(schedule_today)
        current_tomorrow_hash = checker._calculate_schedule_hash(schedule_tomorrow) if schedule_tomorrow else None
        
        log(f"🔐 [MANUAL] Хеш поточного графіка: {current_hash}")
        
        last_check = await get_last_check()
        
        # Порівнюємо СЬОГОДНІ
        changes_text = None
        if last_check and last_check.get('schedule_data'):
            log("🔄 [MANUAL] Починаю порівняння графіків (СЬОГОДНІ)...")
            old_schedule = last_check['schedule_data']
            if isinstance(old_schedule, str):
                log("⚠️ [MANUAL] schedule_data є рядком, конвертую...")
                try:
                    old_schedule = json.loads(old_schedule)
                except Exception as e:
                    log(f"❌ [MANUAL] Помилка конвертації: {e}")
                    old_schedule = None
            
            if old_schedule:
                try:
                    changes_text = checker._compare_schedules(old_schedule, schedule_today)
                except Exception as e:
                    log(f"❌ [MANUAL] Помилка порівняння: {e}")
                    import traceback
                    log(f"Stack trace: {traceback.format_exc()}")
        else:
            log("📊 [MANUAL] Немає попереднього графіка")
        
        await save_check(result['update_date'], current_hash, schedule_today, current_tomorrow_hash, schedule_tomorrow)
        
        # Для Discord embeds використовуємо naive UTC datetime
        timestamp_now = datetime.now(UKRAINE_TZ).astimezone(pytz.UTC).replace(tzinfo=None)
        timestamp_str = datetime.now(UKRAINE_TZ).strftime('%Y%m%d_%H%M%S')
        
        # Відправляємо СЬОГОДНІ
        update_date_display = result['update_date'] if result.get('update_date') else 'сьогодні'
        
        embed = discord.Embed(
            title=f"📊 Графік оновився {update_date_display} (Ручна перевірка)",
            color=discord.Color.green(),
            timestamp=timestamp_now
        )
        
        if result['update_date']:
            embed.add_field(
                name="📅 Дата оновлення на сайті",
                value=f"`{result['update_date']}`",
                inline=False
            )
        
        if changes_text:
            embed.add_field(
                name="📊 Що змінилось:",
                value=changes_text,
                inline=False
            )
        
        embed.set_footer(text="Ручна перевірка • !check")
        
        file_main = discord.File(
            io.BytesIO(result['screenshot_main']), 
            filename=f"dtek_manual_today_{timestamp_str}.png"
        )
        
        await ctx.send(embed=embed, file=file_main)
        
        # Відправляємо ЗАВТРА якщо є відключення
        if schedule_tomorrow and result.get('screenshot_tomorrow'):
            has_outages = checker._has_any_outages(schedule_tomorrow)
            if has_outages:
                # Порівнюємо з попереднім
                changes_text_tomorrow = None
                if last_check and last_check.get('schedule_tomorrow_data'):
                    old_schedule_tomorrow = last_check['schedule_tomorrow_data']
                    if isinstance(old_schedule_tomorrow, str):
                        try:
                            old_schedule_tomorrow = json.loads(old_schedule_tomorrow)
                        except:
                            old_schedule_tomorrow = None
                    
                    if old_schedule_tomorrow:
                        try:
                            changes_text_tomorrow = checker._compare_schedules(old_schedule_tomorrow, schedule_tomorrow)
                        except:
                            pass
                
                tomorrow_date_display = result['second_date'] if result.get('second_date') else 'завтра'
                
                embed_tomorrow = discord.Embed(
                    title=f"📅 Графік оновився {tomorrow_date_display} (Ручна перевірка)",
                    color=discord.Color.blue(),
                    timestamp=timestamp_now
                )
                
                if changes_text_tomorrow:
                    embed_tomorrow.add_field(
                        name="📊 Що змінилось:",
                        value=changes_text_tomorrow,
                        inline=False
                    )
                
                embed_tomorrow.set_footer(text="Ручна перевірка • !check")
                
                file_tomorrow = discord.File(
                    io.BytesIO(result['screenshot_tomorrow']), 
                    filename=f"dtek_manual_tomorrow_{timestamp_str}.png"
                )
                
                await ctx.send(embed=embed_tomorrow, file=file_tomorrow)
        
    except asyncio.TimeoutError:
        log("⏱️ [MANUAL] Таймаут 4 хвилини")
        error_embed = discord.Embed(
            title="⏱️ Таймаут",
            description="Перевірка зайняла більше 4 хвилин. Спробуйте пізніше.",
            color=discord.Color.dark_gray()
        )
        await ctx.send(embed=error_embed)
    except Exception as e:
        error_embed = discord.Embed(
            title="✖️ Помилка",
            description=f"```{str(e)[:500]}```",
            color=discord.Color.dark_gray()
        )
        await ctx.send(embed=error_embed)

@bot.command(name='info')
async def bot_info(ctx):
    """Інформація про бота"""
    embed = discord.Embed(
        title="ℹ️ Інформація про бота",
        description="Бот для автоматичного моніторингу графіків відключень ДТЕК",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="🏠 Адреса моніторингу",
        value="с. Книжичі, вул. Київська, 168",
        inline=False
    )
    
    embed.add_field(
        name="⏱️ Інтервал перевірки",
        value="Кожні 5 хвилин",
        inline=True
    )
    
    browser_status = "✅ Відкритий" if checker.browser else "✖️ Закритий"
    embed.add_field(
        name="🌐 Статус браузера",
        value=browser_status,
        inline=True
    )
    
    cookies_status = "✅ Збережено" if os.path.exists(checker.cookies_file) else "✖️ Відсутні"
    embed.add_field(
        name="🍪 Куки",
        value=cookies_status,
        inline=True
    )
    
    if checker.last_update_date:
        embed.add_field(
            name="📅 Остання дата на сайті",
            value=f"`{checker.last_update_date}`",
            inline=False
        )
    
    embed.add_field(
        name="🌐 Веб-інтерфейс",
        value=f"Порт: {PORT}\nДля проходження капчі",
        inline=False
    )
    
    embed.add_field(
        name="🔄 Автоматичний перезапуск",
        value="Щодня о 23:58 (для оновлення дати)",
        inline=False
    )
    
    embed.add_field(
        name="📋 Команди",
        value="`!check` - Ручна перевірка\n`!restart` - Перезапуск браузера\n`!info` - Інформація\n`!status` - Детальний статус\n`!stop` - Зупинити (адміни)",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name='status')
async def bot_status(ctx):
    """Детальний статус бота"""
    embed = discord.Embed(
        title="📊 Детальний статус бота",
        color=discord.Color.purple(),
        timestamp=datetime.utcnow()
    )
    
    playwright_status = "✅ Запущено" if checker.playwright else "✖️ Не запущено"
    browser_status = "✅ Відкрито" if checker.browser else "✖️ Закрито"
    page_status = "✅ Завантажено" if checker.page else "✖️ Не завантажено"
    
    embed.add_field(name="Playwright", value=playwright_status, inline=True)
    embed.add_field(name="Browser", value=browser_status, inline=True)
    embed.add_field(name="Page", value=page_status, inline=True)
    
    db_status = "✅ Підключено" if db_pool else "✖️ Не підключено"
    embed.add_field(name="База даних", value=db_status, inline=False)
    
    task_status = "✅ Запущено" if check_schedule.is_running() else "✖️ Зупинено"
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
    restart_browser_task.cancel()
    try:
        await checker._save_cookies()
        await checker.close_browser()
    except:
        pass
    await close_db_pool()
    await bot.close()

@bot.command(name='restart')
async def restart_browser_command(ctx):
    """Ручний перезапуск браузера"""
    if not checker.browser or not checker.page:
        await ctx.send("✖️ Браузер не запущено. Спочатку ініціалізуйте через веб-інтерфейс.")
        return
    
    await ctx.send("🔄 Перезапускаю браузер...")
    log("🎮 [MANUAL] Ручний перезапуск браузера")
    
    success = await checker.restart_browser()
    
    if success:
        await ctx.send("✅ Браузер успішно перезапущено!")
    else:
        await ctx.send("❌ Помилка перезапуску браузера. Перевірте логи.")

if __name__ == '__main__':
    try:
        log("")
        log("="*60)
        log("🤖 ЗАПУСК DISCORD БОТА DTEK")
        log("="*60)
        now = datetime.now(UKRAINE_TZ)
        log(f"📅 Дата і час запуску: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        log(f"🌐 Порт веб-інтерфейсу: {PORT}")
        log(f"📢 Discord канал: {CHANNEL_ID}")
        log(f"💾 База даних: {'✓ Налаштована' if DATABASE_URL else '✗ Не налаштована'}")
        log("="*60)
        log("")
        
        bot.run(DISCORD_TOKEN)
    except KeyboardInterrupt:
        log("")
        log("🛑 Отримано сигнал зупинки...")
    except Exception as e:
        log("")
        log(f"❌ КРИТИЧНА ПОМИЛКА: {e}")
    finally:
        log("")
        log("🧹 Очищення ресурсів...")
        try:
            asyncio.run(checker._save_cookies())
            asyncio.run(checker.close_browser())
            asyncio.run(close_db_pool())
        except:
            pass
        log("✓ Бот зупинено")
        now = datetime.now(UKRAINE_TZ)
        log(f"📅 Час зупинки: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        log("")

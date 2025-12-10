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

# HTTP сервер для Render health checks
async def handle_health(request):
    """Health check endpoint"""
    return web.Response(text="OK", status=200)

async def handle_root(request):
    """Root endpoint"""
    return web.Response(text="DTEK Bot is running!", status=200)

async def start_web_server():
    """Запуск веб-сервера для Render"""
    app = web.Application()
    app.router.add_get('/', handle_root)
    app.router.add_get('/health', handle_health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"✓ Web server запущен на порту {PORT}")

class DTEKChecker:
    def __init__(self):
        self.browser = None
        self.context = None
        self.playwright = None
        self.page = None
        self.is_initialized = False
        self.last_update_date = None
        
    async def init_browser_and_page(self):
        """Инициализация браузера и загрузка страницы ОДИН РАЗ"""
        if self.is_initialized:
            print("ℹ️ Браузер уже инициализирован, пропускаю...")
            return
            
        print("🚀 Инициализирую браузер и загружаю страницу...")
        
        # Инициализация Playwright и браузера
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='uk-UA'
        )
        self.page = await self.context.new_page()
        
        # Открываем страницу
        print("📄 Открываю страницу DTEK...")
        await self.page.goto('https://www.dtek-krem.com.ua/ua/shutdowns', 
                      wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(2)
        
        # Закрываем модальное окно (если есть)
        try:
            print("🔍 Проверяю модальное окно...")
            close_btn = self.page.locator('button.m-attention__close')
            await close_btn.wait_for(state='visible', timeout=5000)
            await close_btn.click()
            print("✓ Модальное окно закрыто")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"ℹ️ Модальное окно не найдено или уже закрыто")
        
        # Закрываем модалку с опросом, если появилась
        await self._close_survey_modal()
        
        # Вводим данные адреса
        await self._fill_address()
        
        # Получаем начальную дату обновления
        self.last_update_date = await self._get_update_date()
        print(f"✓ Начальная дата обновления: {self.last_update_date}")
        
        self.is_initialized = True
        print("✅ Браузер и страница полностью инициализированы!")
    
    async def _fill_address(self):
        """Заполняет форму с адресом"""
        print("📝 Заполняю форму адреса...")
        
        # Вводим город
        print("  → Ввожу город...")
        city_input = self.page.locator('.discon-input-wrapper #city')
        await city_input.wait_for(state='visible', timeout=5000)
        await city_input.click()
        await city_input.clear()
        await city_input.type('книж', delay=100)
        await city_input.dispatch_event('change')
        await asyncio.sleep(1.5)
        
        city_option = self.page.locator('#cityautocomplete-list > div:nth-child(2)')
        await city_option.wait_for(state='visible', timeout=5000)
        await city_option.click()
        await asyncio.sleep(1)
        
        # Вводим улицу
        print("  → Ввожу улицу...")
        street_input = self.page.locator('.discon-input-wrapper #street')
        await street_input.wait_for(state='visible', timeout=5000)
        await street_input.click()
        await street_input.clear()
        await street_input.type('киї', delay=100)
        await street_input.dispatch_event('change')
        await asyncio.sleep(1.5)
        
        street_option = self.page.locator('#streetautocomplete-list > div:nth-child(2)')
        await street_option.wait_for(state='visible', timeout=5000)
        await street_option.click()
        await asyncio.sleep(1)
        
        # Вводим номер дома
        print("  → Ввожу номер дома...")
        house_input = self.page.locator('input#house_num')
        await house_input.wait_for(state='visible', timeout=5000)
        await house_input.click()
        await house_input.clear()
        await house_input.type('168', delay=100)
        await house_input.dispatch_event('change')
        await asyncio.sleep(1.5)
        
        house_option = self.page.locator('#house_numautocomplete-list > div:first-child')
        await house_option.wait_for(state='visible', timeout=5000)
        await house_option.click()
        await asyncio.sleep(3)
        
        print("✓ Форма заполнена")
    
    async def _get_update_date(self):
        """Получает дату обновления со страницы"""
        try:
            update_elem = self.page.locator('span.update')
            await update_elem.wait_for(state='visible', timeout=10000)
            update_date = await update_elem.text_content()
            return update_date.strip()
        except Exception as e:
            print(f"⚠ Не удалось получить дату обновления: {e}")
            return None
    
    def crop_screenshot(self, screenshot_bytes, top_crop=300, bottom_crop=400, left_crop=0, right_crop=0):
        """Обрезает скриншот: убирает верх (шапку) и низ (футер)"""
        try:
            image = Image.open(io.BytesIO(screenshot_bytes))
            width, height = image.size
            
            left = left_crop
            top = top_crop
            right = width - right_crop
            bottom = height - bottom_crop
            
            print(f"  📐 Обрезаю: {width}x{height} -> {right-left}x{bottom-top}")
            
            cropped = image.crop((left, top, right, bottom))
            
            output = io.BytesIO()
            cropped.save(output, format='PNG', optimize=True, quality=95)
            return output.getvalue()
        except Exception as e:
            print(f"⚠ Ошибка при обрезке: {e}")
            return screenshot_bytes
    
    async def check_for_updates(self):
        """Проверяет, изменилась ли дата обновления на ОТКРЫТОЙ странице"""
        if not self.is_initialized:
            print("⚠️ Браузер не инициализирован! Инициализирую...")
            await self.init_browser_and_page()
            return None
        
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Проверяю обновления...")
            
            # Закрываем модалку с опросом, если появилась
            await self._close_survey_modal()
            
            # Получаем текущую дату обновления
            current_date = await self._get_update_date()
            
            if not current_date:
                print("⚠️ Не удалось получить дату обновления")
                return None
            
            print(f"  📅 Текущая дата на сайте: {current_date}")
            print(f"  📅 Последняя известная дата: {self.last_update_date}")
            
            # Проверяем, изменилась ли дата
            if current_date != self.last_update_date:
                print("🔔 ОБНАРУЖЕНО ОБНОВЛЕНИЕ!")
                self.last_update_date = current_date
                
                # Делаем скриншоты
                return await self._capture_screenshots(current_date)
            else:
                print("✓ Изменений нет")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка при проверке обновлений: {e}")
            # При ошибке пытаемся переинициализировать
            self.is_initialized = False
            await self.close_browser()
            raise
    
    async def _close_survey_modal(self):
        """Закрывает модальное окно с опросом, если оно появилось"""
        try:
            # Проверяем, появилось ли модальное окно с опросом
            modal_container = self.page.locator('#modal-questionnaire-welcome-18 .modal__container')
            
            # Проверяем с коротким таймаутом (не ждем долго)
            is_visible = await modal_container.is_visible()
            
            if is_visible:
                print("  🔔 Обнаружено модальное окно с опросом, закрываю...")
                close_btn = self.page.locator('#modal-questionnaire-welcome-7 .modal__close')
                await close_btn.click()
                await asyncio.sleep(1)
                print("  ✓ Модальное окно с опросом закрыто")
                return True
        except Exception as e:
            # Если модалки нет или ошибка - это нормально, просто игнорируем
            pass
        return False
    
    async def _capture_screenshots(self, update_date):
        """Делает скриншоты обоих графиков"""
        print("📸 Делаю скриншоты...")
        
        # Ждем загрузки графика
        await asyncio.sleep(2)
        
        # Закрываем модалку с опросом, если появилась
        await self._close_survey_modal()
        
        # Скриншот основного графика (сегодня)
        print("  → Скриншот сегодняшнего графика...")
        screenshot_main = await self.page.screenshot(full_page=True, type='png')
        screenshot_main_cropped = self.crop_screenshot(screenshot_main, top_crop=300, bottom_crop=400)
        
        # Кликаем на второй график (завтра)
        screenshot_tomorrow_cropped = None
        second_date = None
        
        try:
            print("  → Переключаюсь на график завтра...")
            date_selector = self.page.locator('div.date:nth-child(2)')
            await date_selector.wait_for(state='visible', timeout=10000)
            
            second_date = await date_selector.text_content()
            second_date = second_date.strip()
            
            await date_selector.click()
            await asyncio.sleep(3)
            
            # Закрываем модалку, если появилась после клика
            await self._close_survey_modal()
            
            print("  → Скриншот завтрашнего графика...")
            screenshot_tomorrow = await self.page.screenshot(full_page=True, type='png')
            screenshot_tomorrow_cropped = self.crop_screenshot(screenshot_tomorrow, top_crop=300, bottom_crop=400)
            
            # ВОЗВРАЩАЕМСЯ на первый график (сегодняшний)
            print("  → Возвращаюсь на сегодняшний график...")
            first_date_selector = self.page.locator('div.date:nth-child(1)')
            await first_date_selector.click()
            await asyncio.sleep(2)
            print("  ✓ Вернулся на сегодняшний график")
            
        except Exception as e:
            print(f"⚠ Не удалось получить второй график: {e}")
        
        print("✅ Скриншоты готовы!")
        
        return {
            'screenshot_main': screenshot_main_cropped,
            'screenshot_tomorrow': screenshot_tomorrow_cropped,
            'update_date': update_date,
            'second_date': second_date,
            'timestamp': datetime.now().isoformat()
        }
    
    async def force_reload(self):
        """Принудительная перезагрузка страницы (для ручной команды)"""
        print("🔄 Принудительная перезагрузка страницы...")
        
        if not self.is_initialized:
            await self.init_browser_and_page()
            return await self._capture_screenshots(self.last_update_date)
        
        # Перезагружаем страницу
        await self.page.reload(wait_until='domcontentloaded')
        await asyncio.sleep(2)
        
        # Закрываем модалку с предупреждением, если есть
        try:
            close_btn = self.page.locator('button.m-attention__close')
            await close_btn.wait_for(state='visible', timeout=3000)
            await close_btn.click()
            await asyncio.sleep(1)
        except:
            pass
        
        # Закрываем модалку с опросом, если есть
        await self._close_survey_modal()
        
        # Заполняем форму заново
        await self._fill_address()
        
        # Получаем дату и делаем скриншоты
        update_date = await self._get_update_date()
        self.last_update_date = update_date
        
        return await self._capture_screenshots(update_date)
    
    async def close_browser(self):
        """Закрытие браузера"""
        print("🔻 Закрываю браузер...")
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            self.is_initialized = False
            print("✓ Браузер закрыт")
        except Exception as e:
            print(f"⚠ Ошибка при закрытии браузера: {e}")

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
    await init_db_pool()
    await start_web_server()
    # Инициализируем браузер сразу при старте
    await checker.init_browser_and_page()
    check_schedule.start()

@tasks.loop(minutes=5)
async def check_schedule():
    """Периодическая проверка каждые 5 минут (БЕЗ перезагрузки страницы!)"""
    channel = None
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            print(f"❌ Канал {CHANNEL_ID} не найден!")
            return
        
        print(f"\n{'='*60}")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔍 Автопроверка")
        print(f"{'='*60}")
        
        # Просто проверяем обновления на открытой странице
        result = await checker.check_for_updates()
        
        # Если обновлений нет, result будет None
        if not result:
            print(f"{'='*60}\n")
            return
        
        # Если есть обновления - сохраняем в БД
        await save_check(result['update_date'])
        
        # Отправляем уведомление
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
        
        # Отправляем основной скриншот
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_main = discord.File(
            io.BytesIO(result['screenshot_main']), 
            filename=f"dtek_today_{timestamp_str}.png"
        )
        
        await channel.send(embed=embed, file=file_main)
        
        # Отправляем второй скриншот, если есть
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
        
        print(f"✅ Уведомление отправлено!")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"❌ Ошибка в check_schedule: {e}")
        import traceback
        traceback.print_exc()
        
        if channel:
            try:
                error_embed = discord.Embed(
                    title="⚠️ Помилка перевірки",
                    description=f"Не вдалося виконати перевірку. Спробую знову за 5 хвилин.\n```{str(e)[:200]}```",
                    color=discord.Color.red(),
                    timestamp=datetime.now()
                )
                await channel.send(embed=error_embed)
            except:
                print("Не удалось отправить сообщение об ошибке")

@check_schedule.before_loop
async def before_check_schedule():
    """Ждем, пока бот будет готов"""
    await bot.wait_until_ready()
    print("⏳ Ожидание готовности бота...")

@bot.command(name='check')
async def manual_check(ctx):
    """Ручная проверка по команде !check (с принудительной перезагрузкой)"""
    await ctx.send("⏳ Починаю перевірку графіка відключень...")
    
    try:
        # Принудительная перезагрузка страницы
        result = await asyncio.wait_for(checker.force_reload(), timeout=120)
        
        # Обновляем БД
        await save_check(result['update_date'])
        
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
        
        # Отправляем скриншоты
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
            description="Перевірка зайняла більше 2 хвилин. Спробуйте ще раз.",
            color=discord.Color.orange()
        )
        await ctx.send(embed=error_embed)
    except Exception as e:
        import traceback
        error_text = traceback.format_exc()
        print(f"Ошибка в manual_check:\n{error_text}")
        
        error_embed = discord.Embed(
            title="❌ Помилка",
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
    
    browser_status = "✅ Постійно відкритий (економія запитів)" if checker.is_initialized else "❌ Не ініціалізований"
    
    embed.add_field(
        name="🌐 Режим роботи",
        value=browser_status,
        inline=True
    )
    
    embed.add_field(
        name="🛡️ Захист",
        value="Автоматичне закриття модальних вікон та опитувань",
        inline=True
    )
    
    if checker.last_update_date:
        embed.add_field(
            name="🕐 Поточна дата на сайті",
            value=f"`{checker.last_update_date}`",
            inline=False
        )
    
    embed.add_field(
        name="📝 Доступні команди",
        value="`!check` - Ручна перевірка з перезавантаженням\n`!info` - Інформація про бота\n`!status` - Детальний статус\n`!restart` - Перезапустити браузер\n`!stop` - Зупинити бота (тільки адміни)",
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
    
    # Статус браузера
    browser_status = "✅ Відкритий і готовий" if checker.is_initialized else "❌ Не ініціалізований"
    embed.add_field(name="🌐 Браузер", value=browser_status, inline=True)
    
    # Статус страницы
    page_status = "✅ Завантажено" if checker.page else "❌ Не завантажено"
    embed.add_field(name="📄 Сторінка", value=page_status, inline=True)
    
    # Последняя дата
    last_date = checker.last_update_date or "Невідомо"
    embed.add_field(name="📅 Остання дата на сайті", value=f"`{last_date}`", inline=False)
    
    # БД
    db_status = "✅ Підключено" if db_pool else "❌ Не підключено"
    embed.add_field(name="💾 База даних", value=db_status, inline=True)
    
    # Задача
    task_status = "✅ Запущено" if check_schedule.is_running() else "❌ Зупинено"
    embed.add_field(name="⏱️ Автоперевірка", value=task_status, inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='restart')
async def restart_browser(ctx):
    """Перезапуск браузера"""
    await ctx.send("🔄 Перезапускаю браузер...")
    try:
        await checker.close_browser()
        await asyncio.sleep(2)
        await checker.init_browser_and_page()
        await ctx.send("✅ Браузер перезапущено успішно!")
    except Exception as e:
        await ctx.send(f"❌ Помилка при перезапуску: {str(e)[:200]}")

@bot.command(name='stop')
@commands.has_permissions(administrator=True)
async def stop_bot(ctx):
    """Остановка бота"""
    await ctx.send("🛑 Зупиняю бота...")
    check_schedule.cancel()
    await checker.close_browser()
    await close_db_pool()
    await bot.close()

if __name__ == '__main__':
    try:
        print("🤖 Запуск Discord бота DTEK (режим постоянного браузера)...")
        print(f"📅 Дата: {datetime.now()}")
        bot.run(DISCORD_TOKEN)
    except KeyboardInterrupt:
        print("\n🛑 Остановка бота...")
    finally:
        try:
            asyncio.run(checker.close_browser())
        except:
            pass
        try:
            asyncio.run(close_db_pool())
        except:
            pass

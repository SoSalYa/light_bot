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
        self.page = None  # Добавлено: храним страницу
        self.last_update_date = None  # Добавлено: храним последнюю дату
        
    async def init_browser(self):
        """Инициализация браузера и открытие страницы ОДИН РАЗ"""
        if not self.playwright:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                locale='uk-UA'
            )
            print("✓ Браузер инициализирован")
            
            # Создаем страницу и заполняем форму один раз
            self.page = await self.context.new_page()
            await self._setup_page()
    
    async def _setup_page(self):
        """Настройка страницы - выполняется ОДИН РАЗ при инициализации"""
        print(f"[{datetime.now()}] Начинаю настройку страницы...")
        
        # 1. Открываем страницу
        print("Открываю страницу DTEK...")
        await self.page.goto('https://www.dtek-krem.com.ua/ua/shutdowns', 
                      wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(2)
        
        # 2. Закрываем модальное окно с предупреждением (если есть)
        try:
            print("Проверяю модальное окно с предупреждением...")
            close_btn = self.page.locator('button.m-attention__close')
            await close_btn.wait_for(state='visible', timeout=5000)
            await close_btn.click()
            print("Модальное окно с предупреждением закрыто")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"Модальное окно с предупреждением не найдено")
        
        # 2.5. Закрываем окно с опросом (если появилось)
        try:
            print("Проверяю окно с опросом...")
            survey_close = self.page.locator('#modal-questionnaire-welcome-7 .modal__close')
            await survey_close.wait_for(state='visible', timeout=3000)
            await survey_close.click()
            print("Окно с опросом закрыто")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"Окно с опросом не найдено")
        
        # 3. Вводим ЧАСТИЧНОЕ название города: "княж"
        print("Ввожу город...")
        city_input = self.page.locator('.discon-input-wrapper #city')
        await city_input.wait_for(state='visible', timeout=5000)
        await city_input.click()
        await city_input.clear()
        await city_input.type('княж', delay=100)
        
        await city_input.dispatch_event('change')
        await asyncio.sleep(1.5)
        
        # 4. Кликаем на ВТОРОЙ элемент из выпадающего списка
        print("Выбираю из списка: с. Книжичі (Броварський)...")
        city_option = self.page.locator('#cityautocomplete-list > div:nth-child(2)')
        await city_option.wait_for(state='visible', timeout=5000)
        await city_option.click()
        print("Город выбран")
        await asyncio.sleep(1)
        
        # 5. Вводим ЧАСТИЧНОЕ название улицы (как в Automa: "киї")
        print("Ввожу улицу...")
        street_input = self.page.locator('.discon-input-wrapper #street')
        await street_input.wait_for(state='visible', timeout=5000)
        await street_input.click()
        await street_input.clear()
        await street_input.type('киї', delay=100)
        
        await street_input.dispatch_event('change')
        await asyncio.sleep(1.5)
        
        # 6. Кликаем на ВТОРОЙ элемент из выпадающего списка
        print("Выбираю из списка: вул. Київська...")
        street_option = self.page.locator('#streetautocomplete-list > div:nth-child(2)')
        await street_option.wait_for(state='visible', timeout=5000)
        await street_option.click()
        print("Улица выбрана")
        await asyncio.sleep(1)
        
        # 7. Вводим номер дома полностью (как в Automa: "168")
        print("Ввожу номер дома...")
        house_input = self.page.locator('input#house_num')
        await house_input.wait_for(state='visible', timeout=5000)
        await house_input.click()
        await house_input.clear()
        await house_input.type('168', delay=100)
        
        await house_input.dispatch_event('change')
        await asyncio.sleep(1.5)
        
        # 8. Кликаем на ПЕРВЫЙ элемент из выпадающего списка
        print("Выбираю из списка: 168...")
        house_option = self.page.locator('#house_numautocomplete-list > div:first-child')
        await house_option.wait_for(state='visible', timeout=5000)
        await house_option.click()
        print("Номер дома выбран")
        await asyncio.sleep(3)
        
        # 9. Получаем начальную дату обновления
        print("Получаю дату обновления...")
        try:
            update_elem = self.page.locator('span.update')
            await update_elem.wait_for(state='visible', timeout=10000)
            self.last_update_date = await update_elem.text_content()
            self.last_update_date = self.last_update_date.strip()
            print(f"✓ Дата обновления: {self.last_update_date}")
        except Exception as e:
            print(f"⚠ Не удалось получить дату обновления: {e}")
            self.last_update_date = "Невідомо"
        
        print("✅ Страница настроена и готова к мониторингу!")
    
    async def _close_survey_if_present(self):
        """Закрывает опрос если он появился (без ошибок если его нет)"""
        try:
            modal = self.page.locator('#modal-questionnaire-welcome-18 .modal__container')
            if await modal.is_visible():
                close_btn = self.page.locator('#modal-questionnaire-welcome-7 .modal__close')
                await close_btn.click()
                await asyncio.sleep(0.5)
        except:
            pass
    
    async def check_for_update(self):
        """Проверяет изменилась ли дата НА УЖЕ ОТКРЫТОЙ странице"""
        try:
            # Закрываем опрос если появился
            await self._close_survey_if_present()
            
            # Читаем текущую дату
            update_elem = self.page.locator('span.update')
            await update_elem.wait_for(state='visible', timeout=10000)
            current_date = await update_elem.text_content()
            current_date = current_date.strip()
            
            print(f"Текущая дата: {current_date}, Последняя: {self.last_update_date}")
            
            # Если дата изменилась - возвращаем True
            if current_date != self.last_update_date:
                print("🔔 ОБНОВЛЕНИЕ ОБНАРУЖЕНО!")
                self.last_update_date = current_date
                return True
            return False
        except Exception as e:
            print(f"Ошибка при проверке: {e}")
            return False
    
    def crop_screenshot(self, screenshot_bytes, top_crop=300, bottom_crop=400, left_crop=0, right_crop=0):
        """Обрезает скриншот: убирает верх (шапку) и низ (футер)"""
        try:
            image = Image.open(io.BytesIO(screenshot_bytes))
            width, height = image.size
            
            # Вычисляем новые границы
            left = left_crop
            top = top_crop
            right = width - right_crop
            bottom = height - bottom_crop
            
            print(f"Обрезаю скриншот: {width}x{height} -> {right-left}x{bottom-top}")
            
            # Обрезаем
            cropped = image.crop((left, top, right, bottom))
            
            # Конвертируем обратно в bytes
            output = io.BytesIO()
            cropped.save(output, format='PNG', optimize=True, quality=95)
            return output.getvalue()
        except Exception as e:
            print(f"⚠ Ошибка при обрезке скриншота: {e}")
            return screenshot_bytes
    
    async def make_screenshots(self):
        """Делает скриншоты (вызывается только при обнаружении обновления)"""
        try:
            # Закрываем опрос
            await self._close_survey_if_present()
            
            # Ждем полной загрузки графика
            await asyncio.sleep(1)
            
            # 10. Делаем полноразмерный скриншот страницы (основной график)
            print("Делаю скриншот основного графика...")
            screenshot_main = await self.page.screenshot(full_page=True, type='png')
            screenshot_main_cropped = self.crop_screenshot(screenshot_main, top_crop=300, bottom_crop=400)
            print("✓ Скриншот основного графика готов и обрезан")
            
            # 11. Кликаем на второй элемент div.date для второго графика
            print("Кликаю на второй график (завтра)...")
            second_date = None
            screenshot_tomorrow_cropped = None
            try:
                date_selector = self.page.locator('div.date:nth-child(2)')
                await date_selector.wait_for(state='visible', timeout=10000)
                
                # Получаем текст даты перед кликом
                second_date = await date_selector.text_content()
                second_date = second_date.strip()
                print(f"Дата второго графика: {second_date}")
                
                await date_selector.click()
                await asyncio.sleep(4)  # Ждем загрузки графика
                
                # Закрываем опрос если появился
                await self._close_survey_if_present()
                
                # 12. Делаем второй скриншот
                print("Делаю скриншот второго графика...")
                screenshot_tomorrow = await self.page.screenshot(full_page=True, type='png')
                screenshot_tomorrow_cropped = self.crop_screenshot(screenshot_tomorrow, top_crop=300, bottom_crop=400)
                print("✓ Скриншот второго графика готов и обрезан")
                
                # ВОЗВРАЩАЕМСЯ на первый график
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
            print(f"❌ Ошибка при создании скриншотов: {e}")
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
    """Получает данные последней проверки из БД через Session Pooler"""
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
    """Сохраняет данные проверки в БД через Session Pooler"""
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
    # Инициализируем браузер один раз
    await checker.init_browser()
    check_schedule.start()

@tasks.loop(minutes=5)
async def check_schedule():
    """Периодическая проверка каждые 5 минут"""
    channel = None
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            print(f"❌ Канал {CHANNEL_ID} не найден!")
            return
        
        print(f"\n{'='*50}")
        print(f"[{datetime.now()}] Запуск автоматической проверки...")
        print(f"{'='*50}")
        
        # Проверяем изменилась ли дата
        has_update = await checker.check_for_update()
        
        if not has_update:
            print(f"ℹ️ Без изменений")
            print(f"{'='*50}\n")
            return
        
        # Если есть обновление - делаем скриншоты
        result = await checker.make_screenshots()
        
        # Сохраняем в БД
        await save_check(result['update_date'])
        
        # Формируем embed сообщение
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
        
        # Отправляем основной скриншот (сегодня)
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_main = discord.File(
            io.BytesIO(result['screenshot_main']), 
            filename=f"dtek_today_{timestamp_str}.png"
        )
        
        await channel.send(embed=embed, file=file_main)
        
        # Отправляем второй скриншот (завтра), если есть
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
    """Ручная проверка по команде !check"""
    await ctx.send("⏳ Починаю перевірку графіка відключень...")
    
    try:
        # Принудительно делаем скриншоты
        result = await asyncio.wait_for(checker.make_screenshots(), timeout=120)
        
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
        
        # Отправляем основной скриншот
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_main = discord.File(
            io.BytesIO(result['screenshot_main']), 
            filename=f"dtek_manual_today_{timestamp_str}.png"
        )
        
        await ctx.send(embed=embed, file=file_main)
        
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
    
    # Статус браузера
    browser_status = "✅ Постійно відкритий" if checker.browser else "❌ Закритий"
    
    embed.add_field(
        name="🌐 Статус браузера",
        value=browser_status,
        inline=True
    )
    
    if checker.last_update_date:
        embed.add_field(
            name="🕐 Остання дата на сайті",
            value=f"`{checker.last_update_date}`",
            inline=False
        )
    
    embed.add_field(
        name="📝 Доступні команди",
        value="`!check` - Ручна перевірка\n`!info` - Інформація про бота\n`!status` - Детальний статус\n`!stop` - Зупинити бота (тільки адміни)",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name='status')
async def bot_status(ctx):
    """Детальный статус бота для диагностики"""
    embed = discord.Embed(
        title="🔍 Детальний статус бота",
        color=discord.Color.purple(),
        timestamp=datetime.now()
    )
    
    # Проверяем компоненты
    playwright_status = "✅ Запущен" if checker.playwright else "❌ Не запущен"
    browser_status = "✅ Открыт" if checker.browser else "❌ Закрыт"
    page_status = "✅ Загружена" if checker.page else "❌ Не загружена"
    
    embed.add_field(name="Playwright", value=playwright_status, inline=True)
    embed.add_field(name="Browser", value=browser_status, inline=True)
    embed.add_field(name="Page", value=page_status, inline=True)
    
    # Проверяем БД
    db_status = "✅ Підключено" if db_pool else "❌ Не підключено"
    embed.add_field(name="База даних", value=db_status, inline=False)
    
    # Проверяем задачу
    task_status = "✅ Запущено" if check_schedule.is_running() else "❌ Зупинено"
    embed.add_field(name="Автоматична перевірка", value=task_status, inline=False)
    
    # Последняя дата
    if checker.last_update_date:
        embed.add_field(name="📅 Дата на сайті", value=f"`{checker.last_update_date}`", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='stop')
@commands.has_permissions(administrator=True)
async def stop_bot(ctx):
    """Остановка бота (только для администраторов)"""
    await ctx.send("🛑 Зупиняю бота...")
    check_schedule.cancel()
    try:
        await checker.close_browser()
    except:
        pass
    await close_db_pool()
    await bot.close()

if __name__ == '__main__':
    try:
        print("🤖 Запуск Discord бота DTEK...")
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
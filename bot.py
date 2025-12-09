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
        
    async def init_browser(self):
        """Инициализация браузера"""
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
    
    async def close_browser(self):
        """Закрытие браузера"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
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
    
    async def check_shutdowns(self):
        """Основная функция проверки отключений"""
        await self.init_browser()
        page = await self.context.new_page()
        
        try:
            print(f"[{datetime.now()}] Начинаю проверку...")
            
            # 1. Открываем страницу
            print("Открываю страницу DTEK...")
            await page.goto('https://www.dtek-krem.com.ua/ua/shutdowns', 
                          wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(2)
            
            # 2. Закрываем модальное окно (если есть)
            try:
                print("Проверяю модальное окно...")
                close_btn = page.locator('button.m-attention__close')
                await close_btn.wait_for(state='visible', timeout=5000)
                await close_btn.click()
                print("Модальное окно закрыто")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Модальное окно не найдено или уже закрыто")
            
            # 3. Вводим ЧАСТИЧНОЕ название города
            print("Ввожу город...")
            city_input = page.locator('.discon-input-wrapper #city')
            await city_input.wait_for(state='visible', timeout=5000)
            await city_input.click()
            await city_input.clear()
            await city_input.type('книж', delay=100)
            await city_input.dispatch_event('change')
            await asyncio.sleep(1.5)
            
            # 4. Кликаем на ВТОРОЙ элемент из выпадающего списка
            print("Выбираю из списка: с. Книжичі (Броварський)...")
            city_option = page.locator('#cityautocomplete-list > div:nth-child(2)')
            await city_option.wait_for(state='visible', timeout=5000)
            await city_option.click()
            print("Город выбран")
            await asyncio.sleep(1)
            
            # 5. Вводим ЧАСТИЧНОЕ название улицы
            print("Ввожу улицу...")
            street_input = page.locator('.discon-input-wrapper #street')
            await street_input.wait_for(state='visible', timeout=5000)
            await street_input.click()
            await street_input.clear()
            await street_input.type('киї', delay=100)
            await street_input.dispatch_event('change')
            await asyncio.sleep(1.5)
            
            # 6. Кликаем на ВТОРОЙ элемент из выпадающего списка
            print("Выбираю из списка: вул. Київська...")
            street_option = page.locator('#streetautocomplete-list > div:nth-child(2)')
            await street_option.wait_for(state='visible', timeout=5000)
            await street_option.click()
            print("Улица выбрана")
            await asyncio.sleep(1)
            
            # 7. Вводим номер дома полностью
            print("Ввожу номер дома...")
            house_input = page.locator('input#house_num')
            await house_input.wait_for(state='visible', timeout=5000)
            await house_input.click()
            await house_input.clear()
            await house_input.type('168', delay=100)
            await house_input.dispatch_event('change')
            await asyncio.sleep(1.5)
            
            # 8. Кликаем на ПЕРВЫЙ элемент из выпадающего списка
            print("Выбираю из списка: 168...")
            house_option = page.locator('#house_numautocomplete-list > div:first-child')
            await house_option.wait_for(state='visible', timeout=5000)
            await house_option.click()
            print("Номер дома выбран")
            await asyncio.sleep(3)
            
            # 9. Получаем дату обновления из span.update
            print("Получаю дату обновления...")
            update_date = None
            try:
                update_elem = page.locator('span.update')
                await update_elem.wait_for(state='visible', timeout=10000)
                update_date = await update_elem.text_content()
                update_date = update_date.strip()
                print(f"✓ Дата обновления: {update_date}")
            except Exception as e:
                print(f"⚠ Не удалось получить дату обновления: {e}")
                update_date = "Невідомо"
            
            # 10. Делаем полноразмерный скриншот страницы (основной график)
            print("Делаю скриншот основного графика...")
            screenshot_main = await page.screenshot(full_page=True, type='png')
            screenshot_main_cropped = self.crop_screenshot(screenshot_main, top_crop=300, bottom_crop=400)
            print("✓ Скриншот основного графика готов и обрезан")
            
            # 11. Кликаем на второй элемент div.date для второго графика
            print("Кликаю на второй график (завтра)...")
            second_date = None
            try:
                date_selector = page.locator('div.date:nth-child(2)')
                await date_selector.wait_for(state='visible', timeout=5000)
                
                # Получаем текст даты перед кликом
                second_date = await date_selector.text_content()
                second_date = second_date.strip()
                print(f"Дата второго графика: {second_date}")
                
                await date_selector.click()
                await asyncio.sleep(3)  # Ждем загрузки графика
                
                # 12. Делаем второй скриншот
                print("Делаю скриншот второго графика...")
                screenshot_tomorrow = await page.screenshot(full_page=True, type='png')
                screenshot_tomorrow_cropped = self.crop_screenshot(screenshot_tomorrow, top_crop=300, bottom_crop=400)
                print("✓ Скриншот второго графика готов и обрезан")
            except Exception as e:
                print(f"⚠ Не удалось получить второй график: {e}")
                screenshot_tomorrow_cropped = None
                second_date = None
            
            await page.close()
            
            return {
                'screenshot_main': screenshot_main_cropped,
                'screenshot_tomorrow': screenshot_tomorrow_cropped,
                'update_date': update_date,
                'second_date': second_date,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Ошибка при проверке: {e}")
            await page.close()
            raise

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
    check_schedule.start()

@tasks.loop(minutes=5)
async def check_schedule():
    """Периодическая проверка каждые 5 минут"""
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            print(f"❌ Канал {CHANNEL_ID} не найден!")
            return
        
        print(f"\n{'='*50}")
        print(f"[{datetime.now()}] Запуск автоматической проверки...")
        print(f"{'='*50}")
        
        # Выполняем проверку
        result = await checker.check_shutdowns()
        
        # Получаем последнюю проверку из БД
        last_check = await get_last_check()
        
        # Проверяем, изменилась ли дата обновления
        is_updated = False
        if not last_check or last_check.get('update_date') != result['update_date']:
            is_updated = True
            await save_check(result['update_date'])
            print(f"🔔 ИНФОРМАЦИЯ ОБНОВИЛАСЬ! Старая дата: {last_check.get('update_date') if last_check else 'отсутствует'}, Новая: {result['update_date']}")
        else:
            print(f"ℹ️ Без изменений. Дата обновления: {result['update_date']}")
        
        # Отправляем сообщение только если есть обновление
        if is_updated:
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
            
            print(f"✓ Сообщение отправлено в Discord (обновление: {is_updated})")
        else:
            print(f"ℹ️ Изменений нет, сообщение не отправлено")
        
        print(f"{'='*50}\n")
        
    except Exception as e:
        print(f"❌ Ошибка в check_schedule: {e}")
        import traceback
        traceback.print_exc()
        
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            error_embed = discord.Embed(
                title="❌ Помилка",
                description=f"Не вдалося виконати перевірку:\n```{str(e)}```",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            await channel.send(embed=error_embed)

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
        result = await checker.check_shutdowns()
        
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
        
    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Помилка",
            description=f"```{str(e)}```",
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
    
    last_check = await get_last_check()
    if last_check:
        embed.add_field(
            name="🕐 Остання перевірка",
            value=f"`{last_check.get('update_date', 'Невідомо')}`",
            inline=True
        )
    
    embed.add_field(
        name="📝 Доступні команди",
        value="`!check` - Ручна перевірка\n`!info` - Інформація про бота\n`!stop` - Зупинити бота (тільки адміни)",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name='stop')
@commands.has_permissions(administrator=True)
async def stop_bot(ctx):
    """Остановка бота (только для администраторов)"""
    await ctx.send("🛑 Зупиняю бота...")
    check_schedule.cancel()
    await checker.close_browser()
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
        asyncio.run(checker.close_browser())
        asyncio.run(close_db_pool())

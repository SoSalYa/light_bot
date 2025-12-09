import discord
from discord.ext import commands, tasks
import asyncio
from playwright.async_api import async_playwright
import os
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import io

# Конфигурация
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))
DATABASE_URL = os.getenv('DATABASE_URL')  # Session pooler ссылка из Supabase

# Создание бота
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

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
                print(f"Модальное окно не найдено или уже закрыто: {e}")
            
            # 3. Вводим ЧАСТИЧНОЕ название города (как в Automa: "княж")
            print("Ввожу город...")
            city_input = page.locator('.discon-input-wrapper #city')
            await city_input.wait_for(state='visible', timeout=5000)
            await city_input.click()
            await city_input.clear()
            await city_input.type('княж', delay=100)  # Печатаем по буквам с задержкой
            
            # Триггерим событие change
            await city_input.dispatch_event('change')
            await asyncio.sleep(1.5)  # Ждем появления выпадающего списка
            
            # 4. Кликаем на ВТОРОЙ элемент из выпадающего списка (Книжичі Броварський)
            print("Выбираю из списка: с. Книжичі (Броварський)...")
            city_option = page.locator('#cityautocomplete-list > div:nth-child(2)')
            await city_option.wait_for(state='visible', timeout=5000)
            await city_option.click()
            print("Город выбран")
            await asyncio.sleep(1)
            
            # 5. Вводим ЧАСТИЧНОЕ название улицы (как в Automa: "киї")
            print("Ввожу улицу...")
            street_input = page.locator('.discon-input-wrapper #street')
            await street_input.wait_for(state='visible', timeout=5000)
            await street_input.click()
            await street_input.clear()
            await street_input.type('киї', delay=100)  # Печатаем по буквам
            
            # Триггерим событие change
            await street_input.dispatch_event('change')
            await asyncio.sleep(1.5)  # Ждем появления выпадающего списка
            
            # 6. Кликаем на ВТОРОЙ элемент из выпадающего списка (вул. Київська)
            print("Выбираю из списка: вул. Київська...")
            street_option = page.locator('#streetautocomplete-list > div:nth-child(2)')
            await street_option.wait_for(state='visible', timeout=5000)
            await street_option.click()
            print("Улица выбрана")
            await asyncio.sleep(1)
            
            # 7. Вводим номер дома полностью (как в Automa: "168")
            print("Ввожу номер дома...")
            house_input = page.locator('input#house_num')
            await house_input.wait_for(state='visible', timeout=5000)
            await house_input.click()
            await house_input.clear()
            await house_input.type('168', delay=100)
            
            # Триггерим событие change
            await house_input.dispatch_event('change')
            await asyncio.sleep(1.5)  # Ждем появления выпадающего списка
            
            # 8. Кликаем на ПЕРВЫЙ элемент из выпадающего списка (168)
            print("Выбираю из списка: 168...")
            house_option = page.locator('#house_numautocomplete-list > div:first-child')
            await house_option.wait_for(state='visible', timeout=5000)
            await house_option.click()
            print("Номер дома выбран")
            await asyncio.sleep(3)  # Даем время на загрузку результатов
            
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
            
            # 10. Делаем полноразмерный скриншот страницы
            print("Делаю скриншот...")
            screenshot = await page.screenshot(full_page=True, type='png')
            print("✓ Скриншот готов")
            
            await page.close()
            
            return {
                'screenshot': screenshot,
                'update_date': update_date,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Ошибка при проверке: {e}")
            await page.close()
            raise

checker = DTEKChecker()

def get_db_connection():
    """Создает подключение к PostgreSQL"""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_database():
    """Создает таблицу если её нет"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS dtek_checks (
                id SERIAL PRIMARY KEY,
                update_date TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        print("✓ База данных инициализирована")
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")

def get_last_check():
    """Получает последнюю проверку из БД"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT update_date, created_at 
            FROM dtek_checks 
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        return dict(result) if result else None
    except Exception as e:
        print(f"❌ Ошибка при получении данных из БД: {e}")
        return None

def save_check(update_date):
    """Сохраняет проверку в БД"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO dtek_checks (update_date, created_at)
            VALUES (%s, %s)
        """, (update_date, datetime.now()))
        
        conn.commit()
        cur.close()
        conn.close()
        print(f"✓ Данные сохранены в БД: {update_date}")
    except Exception as e:
        print(f"❌ Ошибка при сохранении в БД: {e}")

@bot.event
async def on_ready():
    print(f'✓ {bot.user} подключен к Discord!')
    print(f'✓ Мониторинг канала: {CHANNEL_ID}')
    print(f'✓ Интервал проверки: каждые 5 минут')
    
    # Инициализируем БД
    init_database()
    
    # Запускаем периодические проверки
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
        last_check = get_last_check()
        
        # Проверяем, изменилась ли информация
        is_updated = False
        if not last_check or last_check.get('update_date') != result['update_date']:
            is_updated = True
            save_check(result['update_date'])
            print(f"🔔 ИНФОРМАЦИЯ ОБНОВИЛАСЬ! Старая дата: {last_check.get('update_date') if last_check else 'отсутствует'}, Новая: {result['update_date']}")
        else:
            print(f"ℹ️  Без изменений. Дата обновления: {result['update_date']}")
        
        # Формируем embed сообщение
        embed = discord.Embed(
            title="⚡ Графік відключень ДТЕК Київські регіональні електромережі",
            description="**📍 Адреса:** с. Книжичі, вул. Київська, 168",
            color=discord.Color.orange() if is_updated else discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        if result['update_date']:
            embed.add_field(
                name="🕐 Дата оновлення на сайті",
                value=f"`{result['update_date']}`",
                inline=False
            )
        
        if is_updated:
            embed.add_field(
                name="✅ Статус",
                value="**🔔 ІНФОРМАЦІЯ ОНОВИЛАСЬ!**",
                inline=False
            )
            embed.set_footer(text="Нова інформація • Автоматична перевірка")
        else:
            embed.add_field(
                name="ℹ️ Статус",
                value="Без змін",
                inline=False
            )
            embed.set_footer(text="Планова перевірка")
        
        # Отправляем скриншот
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        file = discord.File(
            io.BytesIO(result['screenshot']), 
            filename=f"dtek_schedule_{timestamp_str}.png"
        )
        
        await channel.send(embed=embed, file=file)
        print(f"✓ Сообщение отправлено в Discord (обновление: {is_updated})")
        print(f"{'='*50}\n")
        
    except Exception as e:
        print(f"❌ Ошибка в check_schedule: {e}")
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
        file = discord.File(
            io.BytesIO(result['screenshot']), 
            filename=f"dtek_manual_{timestamp_str}.png"
        )
        
        await ctx.send(embed=embed, file=file)
        
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
    
    last_check = get_last_check()
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

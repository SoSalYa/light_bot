import os
import re
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui, Embed, SelectOption
from typing import List, Dict
import asyncpg
import aiohttp
import asyncio
from datetime import datetime, timedelta, time as dtime, timezone
from bs4 import BeautifulSoup
import psutil
from flask import Flask, jsonify
from threading import Thread
import time

# === Helper function for UTC time ===
def utcnow():
    """Возвращает текущее время в UTC (заменяет устаревший datetime.utcnow())"""
    return datetime.now(timezone.utc)

# === Config ===
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
STEAM_API_KEY = os.getenv('STEAM_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')
EPIC_API_URL = 'https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions'
DISCOUNT_CHANNEL_ID = int(os.getenv('DISCOUNT_CHANNEL_ID', '0'))
EPIC_CHANNEL_ID = int(os.getenv('EPIC_CHANNEL_ID', '0'))
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', '0'))
PORT = int(os.getenv('PORT', '10000'))
BIND_TTL_HOURS = int(os.getenv('BIND_TTL_HOURS', '24'))
CACHE_TTL = timedelta(hours=2)
VERIFIED_ROLE = "steam verified"

# === Локализация ===
TEXTS = {
    'en': {
        'not_verified': '❌ You need to link your Steam first! Use `/link_steam`',
        'already_linked': 'ℹ️ You already linked this profile.',
        'cooldown': '⏳ Try again in {hours}h.',
        'invalid_url': '❌ Invalid Steam profile URL.',
        'profile_unavailable': '❌ Profile is unavailable.',
        'confirm_link': 'Do you want to link profile **{name}** as **{discord_name}**?',
        'link_success': '✅ Profile `{name}` linked! Loaded {count} games.',
        'link_cancelled': '❌ Linking cancelled.',
        'not_your_request': 'This is not your request.',
        'profile_not_found': 'ℹ️ Profile not found.',
        'unlink_success': '✅ Profile unlinked.',
        'no_players': 'Nobody plays this game.',
        'no_common_games': 'No games found that all players own.',
        'common_games_title': 'Steam Library - Common Games ({count})',
        'participants': 'Players',
        'page': 'Page {current}/{total}',
        'yes': 'Yes',
        'no': 'No',
        'lang_set': '✅ Language set to English',
        'choose_lang': 'Choose server language:',
        'cmd_link_steam': 'link_steam',
        'cmd_link_desc': 'Link your Steam profile',
        'cmd_link_param': 'Steam profile URL',
        'cmd_unlink_steam': 'unlink_steam',
        'cmd_unlink_desc': 'Unlink Steam',
        'cmd_find_teammates': 'find_teammates',
        'cmd_find_desc': 'Find players',
        'cmd_find_param': 'Game name',
        'cmd_common_games': 'common_games',
        'cmd_common_desc': 'Show common games',
        'cmd_common_param': 'User to compare',
        'hours_visible': '✅ Visible',
        'hours_hidden': '👁️ Hidden',
        'sort_alphabetical': '🔤 Alphabetical',
        'sort_total_hours': '📊 By Total Playtime',
        'sort_your_hours': "⭐ By {user}'s Playtime",
        'timeout_expired': '⏰ This menu has expired',
        'confirmation_expired': '⏰ Confirmation expired',
        'privacy_note': '🔒 Privacy',
        'privacy_text': 'Your profile must be **public** to sync games',
        'profile_info': 'Profile',
        'next_steps': '📊 Next Steps',
        'next_steps_text': '• Use `/common_games` to find games with friends\n• Use `/find_teammates` to find players for a game\n• Your games will sync automatically every 24h',
        'profile_linked': 'Steam Bot • Profile linked',
        'no_profile': 'ℹ️ No Profile Found',
        'no_profile_text': "You don't have a Steam profile linked.\n\nUse `/link_steam` to link your profile!",
        'profile_unlinked_title': '✅ Profile Unlinked',
        'profile_unlinked_desc': 'Your Steam profile has been successfully unlinked.',
        'previous_profile': 'Previous profile',
        'games_removed': '🎮 Games removed',
        'all_synced': 'All synced games',
        'role_removed': '🎖️ Role removed',
        'want_relink': '💡 Want to link again?',
        'relink_text': 'You can re-link your profile anytime using `/link_steam`',
        'ranks': '🏅 Ranks',
        'ranks_text': '🏆 500h+ • 💎 200h+ • ⭐ 100h+ • ✨ 50h+ • 🎯 10h+ • 🆕 <10h',
        'requested_by': 'Requested by',
        'note': 'ℹ️ Note',
        'showing_top': 'Showing top 15 of {total} players',
        'found_players': 'Found {count} player(s)',
        'select_game': '🎮 Select a game',
        'type_to_search': 'Type to search for games...',
        'no_games_found': 'No games found matching "{query}"',
        'cmd_invite_player': 'invite_player',
        'cmd_invite_desc': 'Send a lobby invitation to a player',
        'cmd_invite_param_user': 'Player to invite',
        'cmd_invite_param_lobby': 'Steam lobby link (steam://joinlobby/...)',
        'cmd_create_lobby': 'create_lobby',
        'cmd_create_lobby_desc': 'Create a public lobby announcement',
        'cmd_create_lobby_param': 'Steam lobby link (steam://joinlobby/...)',
        'invalid_lobby_link': '❌ Invalid Steam lobby link! Format: `steam://joinlobby/APPID/LOBBYID/STEAMID`',
        'game_not_found': '❌ Could not find game information for this lobby.',
        'invite_sent': '✅ Invitation sent to {user}!',
        'lobby_created': '✅ Lobby announcement posted!',
        'invite_title': '🎮 Game Invitation',
        'invite_description': '**{inviter}** invites you to play **{game}**!',
        'lobby_title': '🎮 Lobby Open',
        'lobby_description': '**{creator}** is looking for players in **{game}**!',
        'join_button': '🎮 Join Lobby',
        'lobby_info': 'Click the button below to join the lobby',
        'invitation_from': 'Invitation from',
        'lobby_by': 'Lobby by',
        'checking_profile': '🔍 Checking your Steam profile for active lobby...',
        'no_lobby_found': '❌ No active lobby found in your Steam profile!\n\n**How to fix:**\n1. Create a lobby in your game\n2. Make sure your Steam profile is **public**\n3. Make sure you\'re **in the lobby** when using this command\n4. The game must support Steam lobbies',
        'profile_private': '❌ Your Steam profile is private!\n\nPlease set your profile to **public** in Steam settings:\nProfile → Edit Profile → Privacy Settings → My Profile: Public',
        'not_in_game': '❌ You are not currently in a game!\n\nPlease start a game and create a lobby first.',
        'game_no_lobby': '❌ The game you\'re playing doesn\'t have an active joinable lobby.\n\nMake sure:\n• You created a lobby in the game\n• The lobby is set to "Friends Can Join" or "Public"\n• The game supports Steam lobbies',
    },
    'ru': {
        'not_verified': '❌ Сначала привяжите Steam! Используйте `/привязать_steam`',
        'already_linked': 'ℹ️ Вы уже привязали этот профиль.',
        'cooldown': '⏳ Попробуйте снова через {hours}ч.',
        'invalid_url': '❌ Некорректная ссылка на профиль Steam.',
        'profile_unavailable': '❌ Профиль недоступен.',
        'confirm_link': 'Подтверждаете привязку профиля **{name}** как **{discord_name}**?',
        'link_success': '✅ Профиль `{name}` привязан! Загружено {count} игр.',
        'link_cancelled': '❌ Привязка отменена.',
        'not_your_request': 'Это не ваш запрос.',
        'profile_not_found': 'ℹ️ Профиль не найден.',
        'unlink_success': '✅ Профиль отвязан.',
        'no_players': 'Никто не играет в эту игру.',
        'no_common_games': 'Нет игр, которые есть у всех игроков.',
        'common_games_title': 'Библиотека Steam - Общие игры ({count})',
        'participants': 'Игроки',
        'page': 'Стр. {current}/{total}',
        'yes': 'Да',
        'no': 'Нет',
        'lang_set': '✅ Язык установлен: Русский',
        'choose_lang': 'Выберите язык сервера:',
        'cmd_link_steam': 'привязать_steam',
        'cmd_link_desc': 'Привязать профиль Steam',
        'cmd_link_param': 'Ссылка на профиль Steam',
        'cmd_unlink_steam': 'отвязать_steam',
        'cmd_unlink_desc': 'Отвязать Steam',
        'cmd_find_teammates': 'найти_тиммейтов',
        'cmd_find_desc': 'Найти игроков',
        'cmd_find_param': 'Название игры',
        'cmd_common_games': 'общие_игры',
        'cmd_common_desc': 'Показать общие игры',
        'cmd_common_param': 'Пользователь для сравнения',
        'hours_visible': '✅ Видимо',
        'hours_hidden': '👁️ Скрыто',
        'sort_alphabetical': '🔤 По алфавиту',
        'sort_total_hours': '📊 По общему времени',
        'sort_your_hours': "⭐ По времени {user}",
        'timeout_expired': '⏰ Это меню истекло',
        'confirmation_expired': '⏰ Подтверждение истекло',
        'privacy_note': '🔒 Приватность',
        'privacy_text': 'Ваш профиль должен быть **публичным** для синхронизации игр',
        'profile_info': 'Профиль',
        'next_steps': '📊 Следующие шаги',
        'next_steps_text': '• Используйте `/общие_игры` для поиска игр с друзьями\n• Используйте `/найти_тиммейтов` для поиска игроков\n• Ваши игры будут синхронизироваться автоматически каждые 24ч',
        'profile_linked': 'Steam Bot • Профиль привязан',
        'no_profile': 'ℹ️ Профиль не найден',
        'no_profile_text': "У вас нет привязанного профиля Steam.\n\nИспользуйте `/привязать_steam` для привязки!",
        'profile_unlinked_title': '✅ Профиль отвязан',
        'profile_unlinked_desc': 'Ваш профиль Steam успешно отвязан.',
        'previous_profile': 'Предыдущий профиль',
        'games_removed': '🎮 Игры удалены',
        'all_synced': 'Все синхронизированные игры',
        'role_removed': '🎖️ Роль удалена',
        'want_relink': '💡 Хотите привязать снова?',
        'relink_text': 'Вы можете перепривязать профиль в любое время используя `/привязать_steam`',
        'ranks': '🏅 Ранги',
        'ranks_text': '🏆 500ч+ • 💎 200ч+ • ⭐ 100ч+ • ✨ 50ч+ • 🎯 10ч+ • 🆕 <10ч',
        'requested_by': 'Запросил',
        'note': 'ℹ️ Примечание',
        'showing_top': 'Показано топ 15 из {total} игроков',
        'found_players': 'Найдено {count} игрок(ов)',
        'select_game': '🎮 Выберите игру',
        'type_to_search': 'Начните вводить название игры...',
        'no_games_found': 'Не найдено игр по запросу "{query}"',
        'cmd_invite_player': 'пригласить_игрока',
        'cmd_invite_desc': 'Отправить приглашение в лобби игроку',
        'cmd_invite_param_user': 'Игрок для приглашения',
        'cmd_invite_param_lobby': 'Ссылка на лобби Steam (steam://joinlobby/...)',
        'cmd_create_lobby': 'создать_лобби',
        'cmd_create_lobby_desc': 'Создать публичное объявление о лобби',
        'cmd_create_lobby_param': 'Ссылка на лобби Steam (steam://joinlobby/...)',
        'invalid_lobby_link': '❌ Неверная ссылка на лобби Steam! Формат: `steam://joinlobby/APPID/LOBBYID/STEAMID`',
        'game_not_found': '❌ Не удалось найти информацию об игре для этого лобби.',
        'invite_sent': '✅ Приглашение отправлено {user}!',
        'lobby_created': '✅ Объявление о лобби опубликовано!',
        'invite_title': '🎮 Приглашение в игру',
        'invite_description': '**{inviter}** приглашает вас поиграть в **{game}**!',
        'lobby_title': '🎮 Лобби открыто',
        'lobby_description': '**{creator}** ищет игроков в **{game}**!',
        'join_button': '🎮 Присоединиться к лобби',
        'lobby_info': 'Нажмите на кнопку ниже, чтобы присоединиться к лобби',
        'invitation_from': 'Приглашение от',
        'lobby_by': 'Лобби создал',
        'checking_profile': '🔍 Проверяю ваш профиль Steam на активное лобби...',
        'no_lobby_found': '❌ Активное лобби не найдено в вашем профиле Steam!\n\n**Как исправить:**\n1. Создайте лобби в игре\n2. Убедитесь что ваш профиль Steam **публичный**\n3. Убедитесь что вы **в лобби** при использовании команды\n4. Игра должна поддерживать Steam лобби',
        'profile_private': '❌ Ваш профиль Steam приватный!\n\nПожалуйста, установите профиль как **публичный** в настройках Steam:\nПрофиль → Редактировать профиль → Настройки приватности → Мой профиль: Публичный',
        'not_in_game': '❌ Вы сейчас не в игре!\n\nПожалуйста, запустите игру и создайте лобби сначала.',
        'game_no_lobby': '❌ В игре, в которую вы играете, нет активного доступного лобби.\n\nУбедитесь что:\n• Вы создали лобби в игре\n• Лобби установлено как "Друзья могут присоединиться" или "Публичное"\n• Игра поддерживает Steam лобби',
    },
    'ua': {
        'not_verified': "❌ Спочатку прив'яжіть Steam! Використовуйте `/привязати_steam`",
        'already_linked': "ℹ️ Ви вже прив'язали цей профіль.",
        'cooldown': '⏳ Спробуйте знову через {hours}год.',
        'invalid_url': '❌ Некоректне посилання на профіль Steam.',
        'profile_unavailable': '❌ Профіль недоступний.',
        'confirm_link': "Підтверджуєте прив'язку профілю **{name}** як **{discord_name}**?",
        'link_success': "✅ Профіль `{name}` прив'язано! Завантажено {count} ігор.",
        'link_cancelled': "❌ Прив'язку скасовано.",
        'not_your_request': 'Це не ваш запит.',
        'profile_not_found': 'ℹ️ Профіль не знайдено.',
        'unlink_success': "✅ Профіль відв'язано.",
        'no_players': 'Ніхто не грає в цю гру.',
        'no_common_games': 'Немає ігор, які є у всіх гравців.',
        'common_games_title': 'Бібліотека Steam - Спільні ігри ({count})',
        'participants': 'Гравці',
        'page': 'Стор. {current}/{total}',
        'yes': 'Так',
        'no': 'Ні',
        'lang_set': '✅ Мову встановлено: Українська',
        'choose_lang': 'Оберіть мову сервера:',
        'cmd_link_steam': 'привязати_steam',
        'cmd_link_desc': "Прив'язати профіль Steam",
        'cmd_link_param': 'Посилання на профіль Steam',
        'cmd_unlink_steam': 'відвязати_steam',
        'cmd_unlink_desc': "Від'язати Steam",
        'cmd_find_teammates': 'знайти_тіммейтів',
        'cmd_find_desc': 'Знайти гравців',
        'cmd_find_param': 'Назва гри',
        'cmd_common_games': 'спільні_ігри',
        'cmd_common_desc': 'Показати спільні ігри',
        'cmd_common_param': 'Користувач для порівняння',
        'hours_visible': '✅ Видимо',
        'hours_hidden': '👁️ Приховано',
        'sort_alphabetical': '🔤 За алфавітом',
        'sort_total_hours': '📊 За загальним часом',
        'sort_your_hours': "⭐ За часом {user}",
        'timeout_expired': '⏰ Це меню закінчилось',
        'confirmation_expired': '⏰ Підтвердження закінчилось',
        'privacy_note': '🔒 Приватність',
        'privacy_text': 'Ваш профіль має бути **публічним** для синхронізації ігор',
        'profile_info': 'Профіль',
        'next_steps': '📊 Наступні кроки',
        'next_steps_text': '• Використовуйте `/спільні_ігри` для пошуку ігор з друзями\n• Використовуйте `/знайти_тіммейтів` для пошуку гравців\n• Ваші ігри будуть синхронізуватись автоматично кожні 24г',
        'profile_linked': "Steam Bot • Профіль прив'язано",
        'no_profile': 'ℹ️ Профіль не знайдено',
        'no_profile_text': "У вас немає прив'язаного профілю Steam.\n\nВикористовуйте `/привязати_steam` для прив'язки!",
        'profile_unlinked_title': "✅ Профіль відв'язано",
        'profile_unlinked_desc': "Ваш профіль Steam успішно відв'язано.",
        'previous_profile': 'Попередній профіль',
        'games_removed': '🎮 Ігри видалено',
        'all_synced': 'Всі синхронізовані ігри',
        'role_removed': '🎖️ Роль видалено',
        'want_relink': "💡 Хочете прив'язати знову?",
        'relink_text': "Ви можете перепривʼязати профіль в будь-який час використовуючи `/привязати_steam`",
        'ranks': '🏅 Ранги',
        'ranks_text': '🏆 500г+ • 💎 200г+ • ⭐ 100г+ • ✨ 50г+ • 🎯 10г+ • 🆕 <10г',
        'requested_by': 'Запитав',
        'note': 'ℹ️ Примітка',
        'showing_top': 'Показано топ 15 з {total} гравців',
        'found_players': 'Знайдено {count} гравець(ів)',
        'select_game': '🎮 Оберіть гру',
        'type_to_search': 'Почніть вводити назву гри...',
        'no_games_found': 'Не знайдено ігор за запитом "{query}"',
        'cmd_invite_player': 'запросити_гравця',
        'cmd_invite_desc': 'Надіслати запрошення в лобі гравцю',
        'cmd_invite_param_user': 'Гравець для запрошення',
        'cmd_invite_param_lobby': 'Посилання на лобі Steam (steam://joinlobby/...)',
        'cmd_create_lobby': 'створити_лобі',
        'cmd_create_lobby_desc': 'Створити публічне оголошення про лобі',
        'cmd_create_lobby_param': 'Посилання на лобі Steam (steam://joinlobby/...)',
        'invalid_lobby_link': '❌ Невірне посилання на лобі Steam! Формат: `steam://joinlobby/APPID/LOBBYID/STEAMID`',
        'game_not_found': '❌ Не вдалося знайти інформацію про гру для цього лобі.',
        'invite_sent': '✅ Запрошення надіслано {user}!',
        'lobby_created': '✅ Оголошення про лобі опубліковано!',
        'invite_title': '🎮 Запрошення в гру',
        'invite_description': '**{inviter}** запрошує вас пограти в **{game}**!',
        'lobby_title': '🎮 Лобі відкрито',
        'lobby_description': '**{creator}** шукає гравців в **{game}**!',
        'join_button': '🎮 Приєднатися до лобі',
        'lobby_info': 'Натисніть на кнопку нижче, щоб приєднатися до лобі',
        'invitation_from': 'Запрошення від',
        'lobby_by': 'Лобі створив',
        'checking_profile': '🔍 Перевіряю ваш профіль Steam на активне лобі...',
        'no_lobby_found': '❌ Активне лобі не знайдено у вашому профілі Steam!\n\n**Як виправити:**\n1. Створіть лобі в грі\n2. Переконайтесь що ваш профіль Steam **публічний**\n3. Переконайтесь що ви **в лобі** при використанні команди\n4. Гра повинна підтримувати Steam лобі',
        'profile_private': '❌ Ваш профіль Steam приватний!\n\nБудь ласка, встановіть профіль як **публічний** в налаштуваннях Steam:\nПрофіль → Редагувати профіль → Налаштування приватності → Мій профіль: Публічний',
        'not_in_game': '❌ Ви зараз не в грі!\n\nБудь ласка, запустіть гру і створіть лобі спочатку.',
        'game_no_lobby': '❌ У грі, в яку ви граєте, немає активного доступного лобі.\n\nПереконайтесь що:\n• Ви створили лобі в грі\n• Лобі встановлено як "Друзі можуть приєднатися" або "Публічне"\n• Гра підтримує Steam лобі',
    }
}

# === Intents ===
INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.presences = True
INTENTS.message_content = True
INTENTS.reactions = True

# === Bot Setup ===
bot = commands.Bot(command_prefix='/', intents=INTENTS)
db_pool: asyncpg.Pool = None

# === Cache ===
steam_cache = {}
PAGINATION_VIEWS = {}
server_langs = {}

# === Flask Keep-Alive ===
app = Flask(__name__)
bot_ready = False

@app.route('/')
def index():
    return jsonify({
        'status': 'ok',
        'bot_ready': bot_ready,
        'timestamp': utcnow().isoformat()
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy' if bot_ready else 'starting',
        'uptime': time.time()
    })

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# === Helpers ===
STEAM_URL_REGEX = re.compile(r'^(?:https?://)?steamcommunity\.com/(?:id|profiles)/([\w\-]+)/?$')

def t(guild_id: int, key: str, **kwargs) -> str:
    lang = server_langs.get(guild_id, 'en')
    text = TEXTS.get(lang, TEXTS['en']).get(key, key)
    return text.format(**kwargs) if kwargs else text

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS profiles (
                discord_id BIGINT PRIMARY KEY,
                steam_url TEXT,
                last_bound TIMESTAMP
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS games (
                discord_id BIGINT,
                appid INTEGER,
                game_name TEXT,
                playtime INTEGER,
                icon_hash TEXT,
                PRIMARY KEY (discord_id, appid)
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS server_settings (
                guild_id BIGINT PRIMARY KEY,
                language TEXT DEFAULT 'en'
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS sent_sales (
                game_link TEXT PRIMARY KEY,
                discount_end TIMESTAMP
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS sent_epic (
                game_title TEXT PRIMARY KEY,
                offer_end TIMESTAMP
            )
        ''')
        
        rows = await conn.fetch('SELECT guild_id, language FROM server_settings')
        for row in rows:
            server_langs[row['guild_id']] = row['language']
    
    print("✓ Database pool created and tables verified")

async def resolve_steamid(identifier: str) -> str | None:
    if identifier.isdigit():
        return identifier
    async with aiohttp.ClientSession() as session:
        async with session.get(
            'https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/',
            params={'key': STEAM_API_KEY, 'vanityurl': identifier}
        ) as resp:
            if resp.ok:
                data = await resp.json()
                return data.get('response', {}).get('steamid')
    return None

async def fetch_owned_games(steamid: str) -> dict:
    now = utcnow()
    if steamid in steam_cache and now - steam_cache[steamid][0] < CACHE_TTL:
        return steam_cache[steamid][1]
    
    async with aiohttp.ClientSession() as session:
        async with session.get(
            'https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/',
            params={
                'key': STEAM_API_KEY,
                'steamid': steamid,
                'include_appinfo': 'true',
                'include_played_free_games': 'true'
            }
        ) as resp:
            if resp.ok:
                data = await resp.json()
                games = data.get('response', {}).get('games', [])
                result = {}
                for g in games:
                    appid = g['appid']
                    name = g['name']
                    hours = g['playtime_forever'] // 60
                    icon_hash = g.get('img_icon_url', '')
                    result[appid] = (name, hours, icon_hash)
                steam_cache[steamid] = (now, result)
                return result
    return {}

def parse_steam_url(url: str) -> str | None:
    m = STEAM_URL_REGEX.match(url)
    return m.group(1) if m else None

async def has_verified_role(member: discord.Member) -> bool:
    return any(r.name.lower() == VERIFIED_ROLE.lower() for r in member.roles)

async def ensure_verified_role(guild: discord.Guild) -> discord.Role:
    role = discord.utils.get(guild.roles, name=VERIFIED_ROLE)
    if not role:
        try:
            role = await guild.create_role(
                name=VERIFIED_ROLE,
                color=discord.Color.blue(),
                reason="Auto-created by Steam Bot"
            )
            print(f"Created role '{VERIFIED_ROLE}' in guild {guild.name}")
        except discord.Forbidden:
            print(f"Missing permissions to create role in {guild.name}")
    return role

# === Database Functions ===
async def get_profile(discord_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow('SELECT * FROM profiles WHERE discord_id = $1', discord_id)

async def save_profile(discord_id: int, steam_url: str):
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO profiles (discord_id, steam_url, last_bound)
            VALUES ($1, $2, NOW())
            ON CONFLICT (discord_id) DO UPDATE SET steam_url = $2, last_bound = NOW()
        ''', discord_id, steam_url)

async def delete_profile(discord_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute('DELETE FROM profiles WHERE discord_id = $1', discord_id)

async def save_games(discord_id: int, games: dict):
    async with db_pool.acquire() as conn:
        await conn.execute('DELETE FROM games WHERE discord_id = $1', discord_id)
        if games:
            await conn.executemany('''
                INSERT INTO games (discord_id, appid, game_name, playtime, icon_hash)
                VALUES ($1, $2, $3, $4, $5)
            ''', [(discord_id, appid, name, hrs, icon) for appid, (name, hrs, icon) in games.items()])

async def get_all_games() -> dict:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch('SELECT discord_id, appid, game_name, playtime, icon_hash FROM games')
        data = {}
        for row in rows:
            uid = row['discord_id']
            data.setdefault(uid, {})[row['appid']] = {
                'name': row['game_name'], 
                'hrs': row['playtime'],
                'icon': row.get('icon_hash', '')
            }
        return data

async def get_games_by_name(game_name: str):
    async with db_pool.acquire() as conn:
        return await conn.fetch(
            'SELECT discord_id, playtime FROM games WHERE LOWER(game_name) = LOWER($1)',
            game_name
        )

async def search_games_by_user(discord_id: int, query: str, limit: int = 25):
    """Поиск игр пользователя по частичному совпадению"""
    async with db_pool.acquire() as conn:
        return await conn.fetch('''
            SELECT appid, game_name, icon_hash 
            FROM games 
            WHERE discord_id = $1 AND LOWER(game_name) LIKE LOWER($2)
            ORDER BY playtime DESC
            LIMIT $3
        ''', discord_id, f'%{query}%', limit)

async def get_game_info_by_appid(appid: int):
    """Получает информацию об игре по appid из базы данных"""
    async with db_pool.acquire() as conn:
        return await conn.fetchrow('''
            SELECT game_name, icon_hash 
            FROM games 
            WHERE appid = $1 
            LIMIT 1
        ''', appid)

def parse_lobby_link(lobby_link: str) -> dict | None:
    """Парсит Steam lobby ссылку и извлекает appid, lobby_id, steam_id"""
    pattern = r'steam://joinlobby/(\d+)/(\d+)/(\d+)'
    match = re.match(pattern, lobby_link.strip())
    
    if match:
        return {
            'appid': int(match.group(1)),
            'lobby_id': match.group(2),
            'steam_id': match.group(3),
            'full_link': lobby_link.strip()
        }
    return None

async def get_lobby_from_profile(discord_id: int) -> dict | None:
    """Получает активное лобби из профиля Steam пользователя"""
    profile = await get_profile(discord_id)
    if not profile:
        return {'error': 'no_profile'}
    
    steam_url = profile['steam_url']
    ident = parse_steam_url(steam_url)
    if not ident:
        return {'error': 'invalid_url'}
    
    steamid = await resolve_steamid(ident)
    if not steamid:
        return {'error': 'invalid_steamid'}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(
            'https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/',
            params={'key': STEAM_API_KEY, 'steamids': steamid}
        ) as resp:
            if not resp.ok:
                return {'error': 'api_error'}
            
            data = await resp.json()
            players = data.get('response', {}).get('players', [])
            
            if not players:
                return {'error': 'player_not_found'}
            
            player = players[0]
            
            if player.get('communityvisibilitystate') != 3:
                return {'error': 'profile_private'}
            
            if 'gameid' not in player:
                return {'error': 'not_in_game'}
            
            appid = int(player['gameid'])
            game_name = player.get('gameextrainfo', 'Unknown Game')
        
        try:
            async with session.get(steam_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.ok:
                    html = await resp.text()
                    
                    lobby_pattern = r'steam://joinlobby/(\d+)/(\d+)/(\d+)'
                    match = re.search(lobby_pattern, html)
                    
                    if match:
                        lobby_appid = int(match.group(1))
                        lobby_id = match.group(2)
                        lobby_steamid = match.group(3)
                        
                        if lobby_appid == appid:
                            return {
                                'appid': appid,
                                'lobby_id': lobby_id,
                                'steam_id': lobby_steamid,
                                'full_link': f'steam://joinlobby/{appid}/{lobby_id}/{lobby_steamid}',
                                'game_name': game_name
                            }
        except Exception as e:
            print(f"Error parsing profile for lobby: {e}")
        
        try:
            async with session.get(
                f'https://steamcommunity.com/profiles/{steamid}',
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.ok:
                    html = await resp.text()
                    
                    js_pattern = r'g_rgProfileData\s*=\s*({[^;]+});'
                    js_match = re.search(js_pattern, html)
                    
                    if js_match:
                        try:
                            import json
                            profile_data = json.loads(js_match.group(1))
                            
                            if 'rich_presence' in profile_data:
                                rp = profile_data['rich_presence']
                                if 'steam_display' in rp and 'joinable' in rp.get('steam_display', '').lower():
                                    return {
                                        'appid': appid,
                                        'lobby_id': '0',
                                        'steam_id': steamid,
                                        'full_link': f'steam://joinlobby/{appid}/0/{steamid}',
                                        'game_name': game_name
                                    }
                        except:
                            pass
        except Exception as e:
            print(f"Error getting rich presence: {e}")
        
        return {'error': 'game_no_lobby', 'game_name': game_name, 'appid': appid}

async def set_server_lang(guild_id: int, lang: str):
    server_langs[guild_id] = lang
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO server_settings (guild_id, language)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET language = $2
        ''', guild_id, lang)

# === Steam Discount API Functions ===
async def get_featured_games() -> List[Dict]:
    """Получает список featured игр через Steam API"""
    url = 'https://store.steampowered.com/api/featured/'
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('specials', {}).get('items', [])
    except Exception as e:
        print(f"Error fetching featured games: {e}")
    
    return []

async def get_app_details(appid: int) -> Dict:
    """Получает детальную информацию об игре"""
    url = f'https://store.steampowered.com/api/appdetails?appids={appid}&cc=us&l=english'
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if str(appid) in data and data[str(appid)].get('success'):
                        return data[str(appid)].get('data', {})
    except Exception as e:
        print(f"Error fetching app {appid} details: {e}")
    
    return {}

async def check_free_promotions() -> List[Dict]:
    """Проверяет игры со 100% скидкой (временно бесплатные)"""
    featured = await get_featured_games()
    free_games = []
    
    for game in featured:
        appid = game.get('id')
        if not appid:
            continue
        
        discount_percent = game.get('discount_percent', 0)
        
        if discount_percent == 100:
            details = await get_app_details(appid)
            
            if details:
                is_free = details.get('is_free', False)
                price_overview = details.get('price_overview', {})
                
                if not is_free and price_overview:
                    final_price = price_overview.get('final', 0)
                    initial_price = price_overview.get('initial', 0)
                    
                    if final_price == 0 and initial_price > 0:
                        free_games.append({
                            'appid': appid,
                            'name': details.get('name', 'Unknown'),
                            'original_price': initial_price / 100,
                            'header_image': details.get('header_image', ''),
                            'short_description': details.get('short_description', ''),
                            'url': f"https://store.steampowered.com/app/{appid}"
                        })
                        
                        print(f"Found 100% discount: {details.get('name')}")
            
            await asyncio.sleep(1.5)
    
    return free_games

# === Views and UI Components ===
class LanguageView(ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=600)
        self.guild_id = guild_id

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        
        try:
            if hasattr(self, 'message') and self.message:
                embed = discord.Embed(
                    title="⏰ Timeout",
                    description="Language selection expired. Use `/set_language` to change it later.",
                    color=0x95a5a6
                )
                await self.message.edit(embed=embed, view=self)
        except:
            pass

    @ui.button(label='🇬🇧 English', style=discord.ButtonStyle.secondary)
    async def english(self, interaction: discord.Interaction, button: ui.Button):
        await set_server_lang(self.guild_id, 'en')
        await interaction.response.send_message(TEXTS['en']['lang_set'], ephemeral=True)
        self.stop()

    @ui.button(label='🇷🇺 Русский', style=discord.ButtonStyle.secondary)
    async def russian(self, interaction: discord.Interaction, button: ui.Button):
        await set_server_lang(self.guild_id, 'ru')
        await interaction.response.send_message(TEXTS['ru']['lang_set'], ephemeral=True)
        self.stop()

    @ui.button(label='🇺🇦 Українська', style=discord.ButtonStyle.secondary)
    async def ukrainian(self, interaction: discord.Interaction, button: ui.Button):
        await set_server_lang(self.guild_id, 'ua')
        await interaction.response.send_message(TEXTS['ua']['lang_set'], ephemeral=True)
        self.stop()

class ConfirmView(ui.View):
    def __init__(self, user_id: int, steam_url: str, profile_name: str, discord_name: str, guild_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.steam_url = steam_url
        self.profile_name = profile_name
        self.discord_name = discord_name
        self.guild_id = guild_id
        
        self.children[0].label = t(guild_id, 'yes')
        self.children[1].label = t(guild_id, 'no')

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        
        try:
            if hasattr(self, 'message') and self.message:
                embed = discord.Embed(
                    title="⏰ " + t(self.guild_id, 'timeout_expired'),
                    description=t(self.guild_id, 'confirmation_expired') + ". Please use `/link_steam` again.",
                    color=0x95a5a6
                )
                await self.message.edit(embed=embed, view=self)
        except:
            pass

    @ui.button(label='Yes', style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(t(self.guild_id, 'not_your_request'), ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        
        await save_profile(self.user_id, self.steam_url)
        
        ident = parse_steam_url(self.steam_url)
        steamid = await resolve_steamid(ident) if ident else None
        games = await fetch_owned_games(steamid) if steamid else {}
        await save_games(self.user_id, games)

        role = await ensure_verified_role(interaction.guild)
        member = interaction.guild.get_member(self.user_id)
        if role and member:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                pass

        success_embed = Embed(
            title="✅ " + t(self.guild_id, 'profile_linked'),
            description=(
                f"**Steam Profile:** `{self.profile_name}`\n"
                f"**Discord:** `{self.discord_name}`\n\n"
                f"🎮 **Games synced:** `{len(games)}`\n"
                f"🎖️ **Role assigned:** `{role.name if role else 'N/A'}`"
            ),
            color=0x00ff00
        )
        success_embed.add_field(
            name=t(self.guild_id, 'next_steps'),
            value=t(self.guild_id, 'next_steps_text'),
            inline=False
        )
        success_embed.set_footer(text=t(self.guild_id, 'profile_linked'))
        success_embed.timestamp = utcnow()
        
        await interaction.followup.send(embed=success_embed, ephemeral=True)
        self.stop()

    @ui.button(label='No', style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(t(self.guild_id, 'not_your_request'), ephemeral=True)
        await interaction.response.send_message(t(self.guild_id, 'link_cancelled'), ephemeral=True)
        self.stop()

class GamesView(ui.View):
    def __init__(self, ctx_user: discord.Member, initial_users: List[discord.Member], guild_id: int):
        super().__init__(timeout=900)
        self.ctx_user = ctx_user
        self.users = initial_users[:6]
        self.pages: List[Embed] = []
        self.page_idx = 0
        self.message = None
        self.guild_id = guild_id
        self.show_hours = False
        self.sort_mode = 'name'
        self.creation_time = utcnow()
        
        self.update_buttons()

    def _get_game_icon_url(self, appid: int, icon_hash: str = '') -> str:
        if icon_hash:
            return f"https://cdn.cloudflare.steamstatic.com/steamcommunity/public/images/apps/{appid}/{icon_hash}.jpg"
        return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/capsule_sm_120.jpg"
    
    def _get_game_store_url(self, appid: int) -> str:
        return f"https://store.steampowered.com/app/{appid}"

    def update_buttons(self):
        self.clear_items()
        
        prev_btn = ui.Button(
            label="◀️",
            style=discord.ButtonStyle.secondary,
            disabled=(self.page_idx == 0 or len(self.pages) <= 1),
            custom_id="prev"
        )
        prev_btn.callback = self.prev_page_callback
        self.add_item(prev_btn)
        
        hours_btn = ui.Button(
            label="⏱️ Hours" if not self.show_hours else "⏱️ Hide",
            style=discord.ButtonStyle.primary if self.show_hours else discord.ButtonStyle.secondary,
            custom_id="toggle_hours"
        )
        hours_btn.callback = self.toggle_hours_callback
        self.add_item(hours_btn)
        
        sort_label = {
            'name': '🔤 A-Z',
            'total_hours': '📊 Total',
            'your_hours': '⭐ Yours'
        }
        sort_btn = ui.Button(
            label=sort_label[self.sort_mode],
            style=discord.ButtonStyle.secondary,
            custom_id="sort"
        )
        sort_btn.callback = self.cycle_sort_callback
        self.add_item(sort_btn)
        
        next_btn = ui.Button(
            label="▶️",
            style=discord.ButtonStyle.secondary,
            disabled=(self.page_idx >= len(self.pages) - 1 or len(self.pages) <= 1),
            custom_id="next"
        )
        next_btn.callback = self.next_page_callback
        self.add_item(next_btn)

    async def prev_page_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx_user.id:
            return await interaction.response.send_message(t(self.guild_id, 'not_your_request'), ephemeral=True)
        
        if self.page_idx > 0:
            self.page_idx -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.page_idx], view=self)

    async def next_page_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx_user.id:
            return await interaction.response.send_message(t(self.guild_id, 'not_your_request'), ephemeral=True)
        
        if self.page_idx < len(self.pages) - 1:
            self.page_idx += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.page_idx], view=self)

    async def toggle_hours_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx_user.id:
            return await interaction.response.send_message(t(self.guild_id, 'not_your_request'), ephemeral=True)
        
        self.show_hours = not self.show_hours
        self.update_buttons()
        await self._build_pages()
        await interaction.response.edit_message(embed=self.pages[self.page_idx], view=self)

    async def cycle_sort_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx_user.id:
            return await interaction.response.send_message(t(self.guild_id, 'not_your_request'), ephemeral=True)
        
        sort_cycle = ['name', 'total_hours', 'your_hours']
        current_idx = sort_cycle.index(self.sort_mode)
        self.sort_mode = sort_cycle[(current_idx + 1) % len(sort_cycle)]
        
        self.page_idx = 0
        self.update_buttons()
        await self._build_pages()
        await interaction.response.edit_message(embed=self.pages[self.page_idx], view=self)

    async def on_timeout(self):
        """Удаляет сообщение после истечения 15 минут"""
        try:
            if self.message:
                await self.message.delete()
                
                if self.message.id in PAGINATION_VIEWS:
                    del PAGINATION_VIEWS[self.message.id]
                    
                print(f"✓ Deleted expired games view message {self.message.id}")
        except discord.NotFound:
            print(f"Message {self.message.id} already deleted")
        except Exception as e:
            print(f"Error deleting expired message: {e}")

    async def _build_pages(self):
        data = await get_all_games()
        sets = [set(data.get(u.id, {})) for u in self.users]
        common = set.intersection(*sets) if sets else set()
        
        if self.sort_mode == 'name':
            sorted_list = sorted(common, key=lambda a: data[self.ctx_user.id][a]['name'].lower())
        elif self.sort_mode == 'total_hours':
            sorted_list = sorted(
                common,
                key=lambda a: sum(data[u.id].get(a, {}).get('hrs', 0) for u in self.users),
                reverse=True
            )
        else:
            sorted_list = sorted(
                common,
                key=lambda a: data[self.ctx_user.id].get(a, {}).get('hrs', 0),
                reverse=True
            )
        
        self.pages.clear()
        per_page = 10
        total = len(sorted_list)
        
        for i in range(0, max(total, 1), per_page):
            chunk = sorted_list[i:i+per_page]
            
            if chunk:
                game_lines = []
                for idx, appid in enumerate(chunk, 1):
                    game_data = data[self.ctx_user.id][appid]
                    game_name = game_data['name']
                    icon_hash = game_data.get('icon', '')
                    game_url = self._get_game_store_url(appid)
                    
                    game_link = f"`{idx}.` [{game_name}]({game_url})"
                    
                    if self.show_hours:
                        hours_info = []
                        for u in self.users:
                            hrs = data[u.id].get(appid, {}).get('hrs', 0)
                            hours_info.append(f"**{u.display_name}**: {hrs}h")
                        
                        game_lines.append(f"{game_link}\n     └ {' • '.join(hours_info)}")
                    else:
                        game_lines.append(game_link)
                
                description = "\n".join(game_lines)
                
                emb = Embed(
                    title=f"📚 {t(self.guild_id, 'common_games_title', count=total)}",
                    description=description,
                    color=0x171a21
                )
                
                if chunk:
                    first_game_data = data[self.ctx_user.id][chunk[0]]
                    first_icon_hash = first_game_data.get('icon', '')
                    if first_icon_hash:
                        large_icon = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{chunk[0]}/header.jpg"
                        emb.set_thumbnail(url=large_icon)
                
                participants_text = " • ".join(f"**{u.display_name}**" for u in self.users)
                emb.add_field(
                    name=f"👥 {t(self.guild_id, 'participants')}",
                    value=participants_text,
                    inline=False
                )
                
                if self.sort_mode == 'name':
                    sort_text = t(self.guild_id, 'sort_alphabetical')
                elif self.sort_mode == 'total_hours':
                    sort_text = t(self.guild_id, 'sort_total_hours')
                else:
                    sort_text = t(self.guild_id, 'sort_your_hours', user=self.ctx_user.display_name)
                
                emb.add_field(
                    name="📋 Sorting",
                    value=sort_text,
                    inline=True
                )
                
                hours_status = t(self.guild_id, 'hours_visible') if self.show_hours else t(self.guild_id, 'hours_hidden')
                emb.add_field(
                    name="⏱️ Playtime",
                    value=hours_status,
                    inline=True
                )
                
                page_num = len(self.pages) + 1
                total_pages = max((total - 1) // per_page + 1, 1)
                
                elapsed = (utcnow() - self.creation_time).total_seconds()
                remaining_minutes = max(0, int((900 - elapsed) / 60))
                
                emb.set_footer(
                    text=f"{t(self.guild_id, 'page', current=page_num, total=total_pages)} • Expires in {remaining_minutes}min",
                )
                emb.timestamp = utcnow()
                
            else:
                emb = Embed(
                    title=f"📚 {t(self.guild_id, 'common_games_title', count=0)}",
                    description=f"😢 {t(self.guild_id, 'no_common_games')}\n\n*Try linking more games or playing together!*",
                    color=0x5c7e8b
                )
            
            self.pages.append(emb)

    async def render(self, interaction: discord.Interaction):
        await self._build_pages()
        
        if not self.pages:
            return await interaction.response.send_message(t(self.guild_id, 'no_common_games'), ephemeral=True)

        self.update_buttons()
        await interaction.response.send_message(embed=self.pages[0], view=self)
        self.message = await interaction.original_response()
        
        PAGINATION_VIEWS[self.message.id] = self

class LobbyJoinView(ui.View):
    """View с кнопкой для присоединения к лобби через steam:// протокол"""
    def __init__(self, lobby_link: str, guild_id: int, timeout: int = 900):
        super().__init__(timeout=timeout)
        self.lobby_link = lobby_link
        self.guild_id = guild_id
        
        join_button = ui.Button(
            label="🎮 Join Lobby",
            style=discord.ButtonStyle.link,
            url=lobby_link,
            emoji="🎮"
        )
        self.add_item(join_button)
        
        copy_button = ui.Button(
            label="📋 Copy Link",
            style=discord.ButtonStyle.secondary,
            custom_id="copy_lobby_link",
            emoji="📋"
        )
        copy_button.callback = self.copy_link_callback
        self.add_item(copy_button)
        
        help_button = ui.Button(
            label="❓ Help",
            style=discord.ButtonStyle.secondary,
            custom_id="lobby_help",
            emoji="❓"
        )
        help_button.callback = self.help_callback
        self.add_item(help_button)
        
        self.message: discord.Message | None = None

    async def copy_link_callback(self, interaction: discord.Interaction):
        """Отправляет ссылку для копирования"""
        await interaction.response.send_message(
            f"**📋 Copy this link:**\n\n{self.lobby_link}\n\n"
            f"**How to use:**\n"
            f"• Desktop: Paste in browser or Win+R\n"
            f"• Mobile: Long press and open with Steam app",
            ephemeral=True
        )

    async def help_callback(self, interaction: discord.Interaction):
        """Показывает подробную инструкцию"""
        help_embed = Embed(
            title="❓ How to Join Steam Lobby",
            description="There are several ways to join the lobby:",
            color=0x0099ff
        )
        
        help_embed.add_field(
            name="🖥️ Desktop (Recommended)",
            value=(
                "**Method 1:** Click 'Join Lobby' button\n"
                "**Method 2:** Click 'Copy Link', then:\n"
                "  • Press `Win+R` (Windows) or `Cmd+Space` (Mac)\n"
                "  • Paste the link and press Enter\n"
                "**Method 3:** Copy link and paste in browser address bar"
            ),
            inline=False
        )
        
        help_embed.add_field(
            name="📱 Mobile",
            value=(
                "1. Click 'Copy Link'\n"
                "2. Long press the link\n"
                "3. Select 'Open with Steam'\n"
                "4. Steam app will open and join the lobby"
            ),
            inline=False
        )
        
        help_embed.add_field(
            name="⚠️ Troubleshooting",
            value=(
                "• Make sure Steam is running\n"
                "• Check you own the game\n"
                "• Verify your Steam profile is public\n"
                "• Try copying the link manually"
            ),
            inline=False
        )
        
        help_embed.set_footer(text="Steam Lobby Helper")
        
        await interaction.response.send_message(embed=help_embed, ephemeral=True)

    async def on_timeout(self):
        """Удаляет кнопки после истечения таймаута"""
        for item in self.children:
            item.disabled = True
        
        if hasattr(self, 'message') and self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"Error updating lobby message on timeout: {e}")

# === Game Autocomplete ===
async def game_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Автозаполнение для поиска игр"""
    if not current:
        return []
    
    games = await search_games_by_user(interaction.user.id, current, 25)
    
    return [
        app_commands.Choice(name=game['game_name'][:100], value=game['game_name'])
        for game in games
    ]

# === Command Handlers ===
async def link_steam_handler(interaction: discord.Interaction, steam_url: str):
    await interaction.response.defer(ephemeral=True)
    gid = interaction.guild_id

    profile = await get_profile(interaction.user.id)
    
    if profile and profile['steam_url'] == steam_url:
        return await interaction.followup.send(t(gid, 'already_linked'), ephemeral=True)

    if profile and profile['last_bound']:
        if utcnow() - profile['last_bound'].replace(tzinfo=None) < timedelta(hours=BIND_TTL_HOURS):
            return await interaction.followup.send(t(gid, 'cooldown', hours=BIND_TTL_HOURS), ephemeral=True)

    if not STEAM_URL_REGEX.match(steam_url):
        return await interaction.followup.send(t(gid, 'invalid_url'), ephemeral=True)

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(steam_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    return await interaction.followup.send(t(gid, 'profile_unavailable'), ephemeral=True)
                html = await r.text()
        except:
            return await interaction.followup.send(t(gid, 'profile_unavailable'), ephemeral=True)

    name_m = re.search(r'<title>Steam Community :: (.*?)</title>', html)
    if not name_m:
        name_m = re.search(r'<span class="actual_persona_name">(.*?)</span>', html)
    if not name_m:
        name_m = re.search(r'"personaname":"(.*?)"', html)
    if not name_m:
        name_m = re.search(r'<meta property="og:title" content="(.*?)"', html)
    
    profile_name = name_m.group(1) if name_m else interaction.user.display_name
    profile_name = profile_name.replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    discord_name = interaction.user.display_name
    
    avatar_m = re.search(r'<link rel="image_src" href="(.*?)"', html)
    avatar_url = avatar_m.group(1) if avatar_m else None
    
    ident = parse_steam_url(steam_url)
    steamid = await resolve_steamid(ident) if ident else None
    
    game_count = 0
    if steamid:
        preview_games = await fetch_owned_games(steamid)
        game_count = len(preview_games)
    
    embed = Embed(
        title="🔗 " + t(gid, 'confirm_link', name=profile_name, discord_name=discord_name),
        description=(
            f"**Steam Profile:** `{profile_name}`\n"
            f"**Discord User:** `{discord_name}`\n\n"
            f"🎮 **Games found:** `{game_count}`\n\n"
            f"*Confirm to link this profile to your Discord account*"
        ),
        color=0x1b2838
    )
    
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    
    embed.add_field(
        name=t(gid, 'privacy_note'),
        value=t(gid, 'privacy_text'),
        inline=False
    )
    
    embed.set_footer(text=f"{t(gid, 'profile_info')}: {steam_url[:50]}...")
    embed.timestamp = utcnow()
    view = ConfirmView(interaction.user.id, steam_url, profile_name, discord_name, gid)
    msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    view.message = msg

async def unlink_steam_handler(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    gid = interaction.guild_id
    
    profile = await get_profile(interaction.user.id)
    if not profile:
        embed = Embed(
            title=t(gid, 'no_profile'),
            description=t(gid, 'no_profile_text'),
            color=0x95a5a6
        )
        return await interaction.followup.send(embed=embed, ephemeral=True)

    steam_url = profile['steam_url']
    await delete_profile(interaction.user.id)
    
    role = discord.utils.get(interaction.guild.roles, name=VERIFIED_ROLE)
    if role:
        try:
            await interaction.user.remove_roles(role)
        except:
            pass
    
    unlink_embed = Embed(
        title=t(gid, 'profile_unlinked_title'),
        description=(
            f"{t(gid, 'profile_unlinked_desc')}\n\n"
            f"**{t(gid, 'previous_profile')}:** `{steam_url[:50]}...`\n"
            f"{t(gid, 'games_removed')}: {t(gid, 'all_synced')}\n"
            f"{t(gid, 'role_removed')}: `{VERIFIED_ROLE}`"
        ),
        color=0xe74c3c
    )
    unlink_embed.add_field(
        name=t(gid, 'want_relink'),
        value=t(gid, 'relink_text'),
        inline=False
    )
    unlink_embed.set_footer(text="Steam Bot • Profile unlinked")
    unlink_embed.timestamp = utcnow()
    
    await interaction.followup.send(embed=unlink_embed, ephemeral=True)

async def find_teammates_handler(interaction: discord.Interaction, game: str):
    gid = interaction.guild_id
    
    if not await has_verified_role(interaction.user):
        return await interaction.response.send_message(t(gid, 'not_verified'), ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    
    rows = await get_games_by_name(game)
    if not rows:
        return await interaction.followup.send(t(gid, 'no_players'), ephemeral=True)
    
    async with db_pool.acquire() as conn:
        game_info = await conn.fetchrow(
            'SELECT appid, icon_hash FROM games WHERE LOWER(game_name) = LOWER($1) LIMIT 1',
            game
        )
    
    appid = game_info['appid'] if game_info else None
    icon_hash = game_info['icon_hash'] if game_info else ''
    
    player_list = []
    for idx, row in enumerate(sorted(rows, key=lambda x: x['playtime'], reverse=True), 1):
        member = interaction.guild.get_member(row['discord_id'])
        if member:
            hrs = row['playtime']
            if hrs > 500:
                rank = "🏆"
            elif hrs > 200:
                rank = "💎"
            elif hrs > 100:
                rank = "⭐"
            elif hrs > 50:
                rank = "✨"
            elif hrs > 10:
                rank = "🎯"
            else:
                rank = "🆕"
            
            player_list.append(f"`#{idx}` {rank} {member.mention} **`{hrs}h`**")
    
    if appid:
        game_url = f"https://store.steampowered.com/app/{appid}"
        title = f"🔍 [**{game}**]({game_url})"
    else:
        title = f"🔍 **{game}**"
    
    embed = Embed(
        title="Find Teammates",
        description=f"{title}\n\n*{t(gid, 'found_players', count=len(player_list))}*\n\n" + "\n".join(player_list[:15]),
        color=0x171a21
    )
    
    if appid and icon_hash:
        header_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
        embed.set_thumbnail(url=header_url)
    
    embed.add_field(
        name=t(gid, 'ranks'),
        value=t(gid, 'ranks_text'),
        inline=False
    )
    
    embed.set_footer(text=f"{t(gid, 'requested_by')} {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
    embed.timestamp = utcnow()
    
    if len(player_list) > 15:
        embed.add_field(
            name=t(gid, 'note'),
            value=t(gid, 'showing_top', total=len(player_list)),
            inline=False
        )
    
    await interaction.followup.send(embed=embed, ephemeral=True)

async def common_games_handler(interaction: discord.Interaction, user: discord.Member):
    gid = interaction.guild_id
    
    if not await has_verified_role(interaction.user):
        return await interaction.response.send_message(t(gid, 'not_verified'), ephemeral=True)
    
    view = GamesView(interaction.user, [interaction.user, user], gid)
    await view.render(interaction)

async def create_lobby_handler(interaction: discord.Interaction):
    """Создает публичное объявление о лобби в канале (автоматически получает лобби)"""
    gid = interaction.guild_id
    
    await interaction.response.defer(ephemeral=True)
    
    status_msg = await interaction.followup.send(t(gid, 'checking_profile'), ephemeral=True)
    
    lobby_result = await get_lobby_from_profile(interaction.user.id)
    
    if not lobby_result or 'error' in lobby_result:
        error_type = lobby_result.get('error', 'unknown') if lobby_result else 'no_profile'
        
        if error_type == 'no_profile':
            return await status_msg.edit(content=t(gid, 'not_verified'))
        elif error_type == 'profile_private':
            return await status_msg.edit(content=t(gid, 'profile_private'))
        elif error_type == 'not_in_game':
            return await status_msg.edit(content=t(gid, 'not_in_game'))
        elif error_type == 'game_no_lobby':
            game_name = lobby_result.get('game_name', 'Unknown')
            return await status_msg.edit(
                content=t(gid, 'game_no_lobby').replace('{game}', game_name)
            )
        else:
            return await status_msg.edit(content=t(gid, 'no_lobby_found'))
    
    appid = lobby_result['appid']
    game_name = lobby_result.get('game_name', 'Unknown Game')
    lobby_link = lobby_result['full_link']
    
    game_info = await get_game_info_by_appid(appid)
    icon_hash = game_info['icon_hash'] if game_info else ''
    
    if game_info and game_info['game_name']:
        game_name = game_info['game_name']
    
    embed = Embed(
        title=t(gid, 'lobby_title'),
        description=t(gid, 'lobby_description', creator=interaction.user.display_name, game=game_name),
        color=0x00d4aa
    )
    
    header_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
    embed.set_image(url=header_url)
    
    if icon_hash:
        icon_url = f"https://cdn.cloudflare.steamstatic.com/steamcommunity/public/images/apps/{appid}/{icon_hash}.jpg"
        embed.set_thumbnail(url=icon_url)
    
    embed.add_field(
        name="🎮 Game Information",
        value=f"**Game:** {game_name}\n**Host:** {interaction.user.mention}\n**Status:** Looking for teammates!",
        inline=False
    )
    
    embed.add_field(
        name="🔗 How to Join",
        value=(
            "**1.** Click the 'Join Lobby' button below\n"
            "**2.** Or click 'Copy Link' and paste it in your browser\n"
            "**3.** Or press Win+R, paste the link, and hit Enter"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📎 Direct Link",
        value=f"`{lobby_link}`",
        inline=False
    )
    
    embed.set_footer(
        text=t(gid, 'lobby_by') + f" {interaction.user.display_name}", 
        icon_url=interaction.user.display_avatar.url
    )
    embed.timestamp = utcnow()
    
    view = LobbyJoinView(lobby_link, gid)
    
    sent_message = await interaction.channel.send(embed=embed, view=view)
    view.message = sent_message
    
    await status_msg.edit(content=t(gid, 'lobby_created'))

async def invite_player_handler(interaction: discord.Interaction, user: discord.Member):
    """Отправляет личное приглашение игроку (автоматически получает лобби из профиля)"""
    gid = interaction.guild_id
    
    await interaction.response.defer(ephemeral=True)
    
    status_msg = await interaction.followup.send(t(gid, 'checking_profile'), ephemeral=True)
    
    lobby_result = await get_lobby_from_profile(interaction.user.id)
    
    if not lobby_result or 'error' in lobby_result:
        error_type = lobby_result.get('error', 'unknown') if lobby_result else 'no_profile'
        
        if error_type == 'no_profile':
            return await status_msg.edit(content=t(gid, 'not_verified'))
        elif error_type == 'profile_private':
            return await status_msg.edit(content=t(gid, 'profile_private'))
        elif error_type == 'not_in_game':
            return await status_msg.edit(content=t(gid, 'not_in_game'))
        elif error_type == 'game_no_lobby':
            game_name = lobby_result.get('game_name', 'Unknown')
            return await status_msg.edit(
                content=t(gid, 'game_no_lobby').replace('{game}', game_name)
            )
        else:
            return await status_msg.edit(content=t(gid, 'no_lobby_found'))
    
    appid = lobby_result['appid']
    game_name = lobby_result.get('game_name', 'Unknown Game')
    lobby_link = lobby_result['full_link']
    
    game_info = await get_game_info_by_appid(appid)
    icon_hash = game_info['icon_hash'] if game_info else ''
    
    if game_info and game_info['game_name']:
        game_name = game_info['game_name']
    
    embed = Embed(
        title=t(gid, 'invite_title'),
        description=t(gid, 'invite_description', inviter=interaction.user.display_name, game=game_name),
        color=0x1b2838
    )
    
    header_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
    embed.set_thumbnail(url=header_url)
    
    embed.add_field(
        name="📋 Lobby Information",
        value=f"**Game:** {game_name}\n**Host:** {interaction.user.mention}",
        inline=False
    )
    
    embed.add_field(
        name="🔗 How to Join",
        value=(
            "**Option 1:** Click the button below\n"
            "**Option 2:** Copy the link and paste it in your browser\n"
            "**Option 3:** Press Win+R, paste the link, and press Enter"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📎 Direct Link",
        value=f"`{lobby_link}`",
        inline=False
    )
    
    embed.set_footer(
        text=t(gid, 'invitation_from') + f" {interaction.user.display_name}", 
        icon_url=interaction.user.display_avatar.url
    )
    embed.timestamp = utcnow()
    
    view = LobbyJoinView(lobby_link, gid)
    
    try:
        sent_message = await user.send(embed=embed, view=view)
        view.message = sent_message
        await status_msg.edit(content=t(gid, 'invite_sent', user=user.mention))
    except discord.Forbidden:
        await status_msg.edit(
            content=f"❌ Could not send invitation to {user.mention}. They may have DMs disabled."
        )

# === Command Registration ===
async def register_commands_for_guild(guild: discord.Guild, lang: str):
    @app_commands.command(name=t(guild.id, 'cmd_link_steam'), description=t(guild.id, 'cmd_link_desc'))
    @app_commands.describe(steam_url=t(guild.id, 'cmd_link_param'))
    async def link_steam_cmd(interaction: discord.Interaction, steam_url: str):
        await link_steam_handler(interaction, steam_url)
    
    @app_commands.command(name=t(guild.id, 'cmd_unlink_steam'), description=t(guild.id, 'cmd_unlink_desc'))
    async def unlink_steam_cmd(interaction: discord.Interaction):
        await unlink_steam_handler(interaction)
    
    @app_commands.command(name=t(guild.id, 'cmd_find_teammates'), description=t(guild.id, 'cmd_find_desc'))
    @app_commands.describe(game=t(guild.id, 'cmd_find_param'))
    @app_commands.autocomplete(game=game_autocomplete)
    async def find_teammates_cmd(interaction: discord.Interaction, game: str):
        await find_teammates_handler(interaction, game)
    
    @app_commands.command(name=t(guild.id, 'cmd_common_games'), description=t(guild.id, 'cmd_common_desc'))
    @app_commands.describe(user=t(guild.id, 'cmd_common_param'))
    async def common_games_cmd(interaction: discord.Interaction, user: discord.Member):
        await common_games_handler(interaction, user)
    
    @app_commands.command(name=t(guild.id, 'cmd_invite_player'), description=t(guild.id, 'cmd_invite_desc'))
    @app_commands.describe(user=t(guild.id, 'cmd_invite_param_user'))
    async def invite_player_cmd(interaction: discord.Interaction, user: discord.Member):
        await invite_player_handler(interaction, user)
    
    @app_commands.command(name=t(guild.id, 'cmd_create_lobby'), description=t(guild.id, 'cmd_create_lobby_desc'))
    async def create_lobby_cmd(interaction: discord.Interaction):
        await create_lobby_handler(interaction)
    
    bot.tree.add_command(link_steam_cmd, guild=guild)
    bot.tree.add_command(unlink_steam_cmd, guild=guild)
    bot.tree.add_command(find_teammates_cmd, guild=guild)
    bot.tree.add_command(common_games_cmd, guild=guild)
    bot.tree.add_command(invite_player_cmd, guild=guild)
    bot.tree.add_command(create_lobby_cmd, guild=guild)
    
    await bot.tree.sync(guild=guild)

# === Global Slash Commands (Register BEFORE on_ready) ===
@bot.tree.command(name='set_language', description='Set server language (Admin only)')
@app_commands.describe(language='Language / Язык')
@app_commands.choices(language=[
    app_commands.Choice(name='🇬🇧 English', value='en'),
    app_commands.Choice(name='🇷🇺 Русский', value='ru'),
    app_commands.Choice(name='🇺🇦 Українська', value='ua'),
])
@app_commands.default_permissions(administrator=True)
async def set_language(interaction: discord.Interaction, language: str):
    await set_server_lang(interaction.guild_id, language)
    await interaction.response.send_message(TEXTS[language]['lang_set'], ephemeral=True)
    
    bot.tree.clear_commands(guild=interaction.guild)
    await register_commands_for_guild(interaction.guild, language)
    await interaction.followup.send("✅ Commands updated to new language!", ephemeral=True)

@bot.tree.command(name='check_discounts', description='Manually check for 100% discounts (Admin only)')
@app_commands.default_permissions(administrator=True)
async def check_discounts_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    try:
        free_games = await check_free_promotions()
        
        if not free_games:
            await interaction.followup.send(
                "✅ Check complete - no new 100% discount games found.",
                ephemeral=True
            )
            return
        
        games_list = "\n".join([
            f"• **{g['name']}** (${g['original_price']:.2f})"
            for g in free_games
        ])
        
        await interaction.followup.send(
            f"🎉 Found {len(free_games)} game(s) with 100% discount:\n\n{games_list}\n\n"
            f"Alerts will be sent to the configured channel.",
            ephemeral=True
        )
        
        if DISCOUNT_CHANNEL_ID > 0:
            await discount_game_check()
        
    except Exception as e:
        await interaction.followup.send(
            f"❌ Error checking discounts: {str(e)}",
            ephemeral=True
        )

# === Events ===
@bot.event
async def on_ready():
    global bot_ready
    print(f'Bot logged in as {bot.user}')
    
    try:
        await init_db()
        print("✓ Database initialized")
    except Exception as e:
        print(f"✗ Database init error: {e}")
        return
    
    print("Starting command sync...")
    try:
        # Синхронизируем глобальные команды
        print("Syncing global commands...")
        await bot.tree.sync()
        print("✓ Global commands synced")
        
        # Регистрируем команды для каждого сервера
        for guild in bot.guilds:
            lang = server_langs.get(guild.id, 'en')
            await register_commands_for_guild(guild, lang)
        
        print(f"✓ Commands synced for {len(bot.guilds)} guilds")
    except Exception as e:
        print(f"✗ Command sync error: {e}")
    
    print("Starting background tasks...")
    
    tasks_to_start = [
        ('daily_link_check', daily_link_check),
        ('discount_game_check', discount_game_check),
        ('cleanup_old_views', cleanup_old_views),
        ('epic_free_check', epic_free_check)
    ]
    
    for task_name, task in tasks_to_start:
        try:
            if not task.is_running():
                task.start()
                print(f"✓ {task_name} started")
        except Exception as e:
            print(f"✗ Error starting {task_name}: {e}")
    
    print(f"✓ Bot ready! Serving {len(bot.guilds)} guilds")
    bot_ready = True

@bot.event
async def on_guild_join(guild: discord.Guild):
    try:
        embed = Embed(
            title="🎮 Steam Bot",
            description="Thanks for adding me! Please choose the server language:\n\n"
                        "Спасибо за добавление! Выберите язык сервера:\n\n"
                        "Дякуємо за додавання! Оберіть мову сервера:",
            color=0x1a9fff
        )
        view = LanguageView(guild.id)
        msg = await guild.owner.send(embed=embed, view=view)
        view.message = msg
    except discord.Forbidden:
        pass

# === Background Tasks ===
@tasks.loop(time=dtime(0, 10))
async def daily_link_check():
    """Ежедневная синхронизация Steam библиотек"""
    async with db_pool.acquire() as conn:
        profiles = await conn.fetch('SELECT discord_id, steam_url FROM profiles')
    
    for p in profiles:
        ident = parse_steam_url(p['steam_url'])
        if not ident:
            continue
        steamid = await resolve_steamid(ident)
        if steamid:
            games = await fetch_owned_games(steamid)
            await save_games(p['discord_id'], games)
        await asyncio.sleep(1)

@tasks.loop(hours=6)
async def discount_game_check():
    """Проверяет Steam на игры со 100% скидкой"""
    ch = bot.get_channel(DISCOUNT_CHANNEL_ID)
    if not ch:
        print("Discord channel not configured for discount alerts")
        return
    
    print("Starting Steam 100% discount check...")
    
    try:
        free_games = await check_free_promotions()
        
        if not free_games:
            print("No 100% discount games found")
            return
        
        async with db_pool.acquire() as conn:
            existing = {
                r['game_link'] 
                for r in await conn.fetch('SELECT game_link FROM sent_sales')
            }
            
            sent_count = 0
            
            for game in free_games:
                game_url = game['url']
                
                if game_url in existing:
                    continue
                
                await conn.execute('''
                    INSERT INTO sent_sales (game_link, discount_end) 
                    VALUES ($1, NOW() + interval '14 days') 
                    ON CONFLICT DO NOTHING
                ''', game_url)
                
                embed = Embed(
                    title="🎉 FREE TO KEEP - 100% OFF!",
                    description=(
                        f"**[{game['name']}]({game_url})**\n\n"
                        f"💵 Regular Price: **${game['original_price']:.2f}**\n"
                        f"✨ Now: **FREE**\n\n"
                        f"{game['short_description'][:200]}...\n\n"
                        f"⏰ **Limited Time Offer - Claim it now!**"
                    ),
                    color=0x00ff00
                )
                
                if game['header_image']:
                    embed.set_image(url=game['header_image'])
                
                embed.set_footer(
                    text="Steam 100% Discount Alert • Claim before it ends!"
                )
                embed.timestamp = utcnow()
                
                try:
                    await ch.send(embed=embed)
                    sent_count += 1
                    print(f"✓ Sent alert for: {game['name']}")
                    
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    print(f"Error sending message for {game['name']}: {e}")
            
            if sent_count > 0:
                print(f"✓ Sent {sent_count} new 100% discount alerts")
            
    except Exception as e:
        print(f"Error in discount_game_check: {e}")
        import traceback
        traceback.print_exc()

@tasks.loop(hours=1)
async def cleanup_old_views():
    """Очищает устаревшие views из кэша"""
    current_time = utcnow()
    to_remove = []
    
    for msg_id, view in PAGINATION_VIEWS.items():
        if hasattr(view, 'message') and view.message:
            try:
                if not view.is_finished():
                    continue
                to_remove.append(msg_id)
            except:
                to_remove.append(msg_id)
    
    for msg_id in to_remove:
        PAGINATION_VIEWS.pop(msg_id, None)
    
    if to_remove:
        print(f"Cleaned up {len(to_remove)} old pagination views")

@tasks.loop(hours=6)
async def epic_free_check():
    """Проверяет бесплатные игры в Epic Games Store"""
    ch = bot.get_channel(EPIC_CHANNEL_ID)
    if not ch:
        return
    
    async with aiohttp.ClientSession() as session:
        async with session.get(EPIC_API_URL) as resp:
            if not resp.ok:
                return
            data = await resp.json()
    
    offers = data.get('data', {}).get('Catalog', {}).get('searchStore', {}).get('elements', [])
    
    async with db_pool.acquire() as conn:
        existing = {r['game_title'] for r in await conn.fetch('SELECT game_title FROM sent_epic')}
        
        for game in offers:
            title = game.get('title')
            if not title or title in existing:
                continue
            
            promos = game.get('promotions') or {}
            for block in promos.get('promotionalOffers', []):
                for o in block.get('promotionalOffers', []):
                    if o.get('discountSetting', {}).get('discountPercentage') == 0:
                        await conn.execute(
                            'INSERT INTO sent_epic (game_title, offer_end) VALUES ($1, $2) ON CONFLICT DO NOTHING',
                            title, utcnow() + timedelta(days=7)
                        )
                        slug = game.get('productSlug') or game.get('catalogNs', {}).get('mappings', [{}])[0].get('pageSlug')
                        url = f"https://www.epicgames.com/store/p/{slug}" if slug else ""
                        
                        embed = Embed(
                            title="🎁 FREE GAME",
                            description=f"**[{title}]({url})**\n\nFree on Epic Games Store!",
                            color=0x00d4aa
                        )
                        embed.set_footer(text="Epic Games")
                        await ch.send(embed=embed)

# === Start ===
if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    bot.run(DISCORD_TOKEN)
    
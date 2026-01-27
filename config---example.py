import os

# ----------------------------
# FILE: config.py
# ----------------------------
# Настройки бота. Этот файл должен лежать рядом с bot.py.

# Токен бота (от @BotFather)
# Т.к. работаем локально, без доступа извне по-умолчанию, заполнять его не требуется
BOT_TOKEN = ''

# Секретный токен для проверки подлинности обновлений от Telegram (в URL вебхука)
TG_SUBSCRIBE_TOKEN = 'anyrandomstring'

# Токен доступа для внешних клиентов (ваших скриптов)
EXTERNAL_ACCESS_TOKEN = 'CHANGE_THIS_TO_A_STRONG_TOKEN'

# Токен админа (для опасных операций: удаление, сброс вебхука)
ADMIN_TOKEN = EXTERNAL_ACCESS_TOKEN

# Папка для данных
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')

# Если True, сообщения не отправляются ботом, а сохраняются в отдельный файл для другого поллера
# Т.к. работаем локально, по-умолчанию установлено в True
SEND_TO_TG_THROUGH_EXTERNAL_POLL = True
# Файл для сообщений внешнего поллера
SEND_TO_TG_THROUGH_EXTERNAL_POLL_MESSAGES_FILE = os.path.join(DATA_DIR, 'externalpoll_to_tg.json')

# Обновлять ли вебхук при каждом запросе (как в оригинале)
# Т.к. работаем локально, по-умолчанию установлено в False
REFRESH_WEBHOOK_ON_EACH_REQUEST = False

# Файл хранилища сообщений
MESSAGES_FILE = os.path.join(DATA_DIR, 'messages.json')

# Файл временной метки вебхука
WEBHOOK_TIMESTAMP_FILE = os.path.join(DATA_DIR, 'last_webhook_set.txt')

# Интервал обновления вебхука (сек)
WEBHOOK_INTERVAL = 1800

# Часовой пояс
APP_TIMEZONE = 'Europe/Moscow'

# Список разрешенных IP (оставьте пустым [], чтобы разрешить всем)
ALLOWED_IPS = [
    # '127.0.0.1',
]

# Настройка локального адреса сервера
LOCAL_SERVER_IP = "127.0.0.1" # Можно сменить на "0.0.0.0", если нужен доступ извне. Это позволит слушать все интерфейсы, а "127.0.0.1" ограничивает подключения только текущей машиной
LOCAL_SERVER_PORT = 12440
LOCAL_SERVER_DEBUG = True
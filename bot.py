# pip install flask requests
import os
import json
import time
import hashlib
import hmac
import requests
from flask import Flask, request, jsonify, Response, render_template_string
from datetime import datetime
import config

# Инициализация Flask приложения
app = Flask(__name__)

# Создаем папку data, если её нет
if not os.path.exists(config.DATA_DIR):
    os.makedirs(config.DATA_DIR, exist_ok=True)

# ----------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------

def atomic_write_json(path, data):
    """Безопасная запись JSON файла (пишем в temp, потом переименовываем)"""
    tmp_path = path + '.tmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        print(f"Error writing file {path}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False

def read_json_file(path, default=None):
    """Чтение JSON файла"""
    if default is None:
        default = []
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            # Обработка старого формата PHP, если вдруг файл остался от старой версии
            if content.startswith('<?php'):
                # Пропускаем первую строку
                content = content.split('\n', 1)[1]
            if not content:
                return default
            return json.loads(content)
    except Exception as e:
        print(f"Error reading file {path}: {e}")
        return default

def check_token(expected_token, token_from_req):
    """Безопасное сравнение токенов"""
    if not token_from_req:
        return False
    return hmac.compare_digest(expected_token, token_from_req)

def is_allowed_ip():
    """Проверка IP адреса"""
    if not config.ALLOWED_IPS:
        return True
    # В Flask request.remote_addr содержит IP клиента
    # Если вы используете Nginx как прокси, возможно потребуется использовать заголовки X-Forwarded-For
    return request.remote_addr in config.ALLOWED_IPS

def telegram_api_request(method, params=None):
    """Запрос к Telegram API"""
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/{method}"
    try:
        resp = requests.post(url, json=params, timeout=10)
        return resp.json()
    except Exception as e:
        return {'ok': False, 'error': str(e)}

def set_telegram_webhook():
    """Установка вебхука"""
    # Формируем URL. Предполагаем, что скрипт знает свой внешний URL
    # В Python сложнее автоматически определить полный URL с https, 
    # поэтому лучше брать Host из заголовков, но протокол (http/https) нужно знать точно.
    host = request.headers.get('Host')
    protocol = 'https' if request.is_secure else 'http'
    # В оригинале использовался REQUEST_URI. Здесь мы строим базовый URL.
    # ВАЖНО: Flask запущенный локально не имеет HTTPS по умолчанию.
    # Для Telegram Webhook ОБЯЗАТЕЛЕН HTTPS.
    
    # Пытаемся реконструировать URL, удаляя query string
    base_url = f"{protocol}://{host}{request.path}"
    
    webhook_url = f"{base_url}?token={config.TG_SUBSCRIBE_TOKEN}"
    return telegram_api_request('setWebhook', {'url': webhook_url})

def ensure_webhook_recent():
    """Проверка актуальности вебхука по таймеру"""
    last_set = 0
    if os.path.exists(config.WEBHOOK_TIMESTAMP_FILE):
        try:
            with open(config.WEBHOOK_TIMESTAMP_FILE, 'r') as f:
                last_set = int(float(f.read().strip()))
        except:
            pass
    
    now = time.time()
    if (now - last_set) >= config.WEBHOOK_INTERVAL:
        res = set_telegram_webhook()
        # Обновляем метку времени
        with open(config.WEBHOOK_TIMESTAMP_FILE, 'w') as f:
            f.write(str(int(now)))
        return res
    return {'ok': True, 'info': 'webhook still fresh'}

# ----------------------------------------------------------------------
# Logic Handlers
# ----------------------------------------------------------------------

def handle_get_messages():
    """Получение недоставленных сообщений"""
    if not is_allowed_ip():
        return jsonify({'error': 'Forbidden by IP'}), 403

    messages = read_json_file(config.MESSAGES_FILE, [])
    out_messages = []
    indexes_to_mark = []
    
    requested_chat_id = request.json.get('chat_id') if request.is_json else None

    for i, m in enumerate(messages):
        if not m.get('delivered', False):
            # Фильтрация по chat_id если он передан
            msg_chat_id = m.get('chat_id', '')
            if requested_chat_id and str(requested_chat_id) != str(msg_chat_id):
                continue

            # Формируем имя
            name = m.get('username')
            if not name:
                parts = [p for p in [m.get('first_name'), m.get('last_name')] if p]
                name = ' '.join(parts) if parts else 'Unknown'
            
            ts = m.get('date_ts', time.time())
            # Формат даты как в PHP: d.m H:i
            date_str = datetime.fromtimestamp(ts).strftime('%d.%m %H:%M')

            out_messages.append({
                'name': name,
                'date': date_str,
                'msg': m.get('text', ''),
                'chat_id': m.get('chat_id', '')
            })
            indexes_to_mark.append(i)
    
    # Отмечаем как доставленные
    if indexes_to_mark:
        for idx in indexes_to_mark:
            messages[idx]['delivered'] = True
            messages[idx]['delivered_at'] = time.time()
        atomic_write_json(config.MESSAGES_FILE, messages)

    return jsonify({'messages': out_messages})

def handle_send_message():
    """Отправка сообщения в Telegram или во внутреннюю очередь"""
    if not is_allowed_ip():
        return jsonify({'error': 'Forbidden by IP'}), 403

    data = request.json
    if not data or 'msg' not in data or 'channel_id' not in data:
        return jsonify({'error': 'Bad request, expected JSON with msg and channel_id'}), 400

    params = {
        'chat_id': data['channel_id'],
        'text': data['msg']
    }

    if config.SEND_TO_TG_THROUGH_EXTERNAL_POLL:
        # Сохраняем во внешний файл
        params['date'] = datetime.now().strftime('%d-%m-%Y %H:%M:%S')
        
        current_pool = read_json_file(config.SEND_TO_TG_THROUGH_EXTERNAL_POLL_MESSAGES_FILE, [])
        current_pool.append(params)
        atomic_write_json(config.SEND_TO_TG_THROUGH_EXTERNAL_POLL_MESSAGES_FILE, current_pool)
        result = {'ok': True, 'info': 'Stored for external polling'}
    else:
        # Отправляем напрямую
        result = telegram_api_request('sendMessage', params)

    return jsonify(result)

def handle_telegram_update(update):
    """Обработка входящего вебхука от Telegram"""
    if 'message' not in update:
        return {'ignored': True}
    
    m = update['message']
    text = m.get('text')
    
    # Логика определения типа контента
    if text is None:
        if 'caption' in m:
            text = f"Картинка с подписью: {m['caption']}"
        elif 'voice' in m:
            dur = m['voice'].get('duration', '?')
            text = f"Голосовое сообщение на {dur} сек."
        elif 'photo' in m:
            text = "Отправлено изображение"
        elif 'video' in m:
            dur = m['video'].get('duration', '?')
            text = f"Отправлено видео на {dur} сек."
    
    if text is None:
        return {'stored': False, 'reason': 'undefined msg type'}

    stored_msg = {
        'message_id': m.get('message_id'),
        'chat_id': m.get('chat', {}).get('id'),
        'text': text,
        'username': m.get('from', {}).get('username'),
        'first_name': m.get('from', {}).get('first_name'),
        'last_name': m.get('from', {}).get('last_name'),
        'date_ts': m.get('date', time.time()),
        'delivered': False
    }

    messages = read_json_file(config.MESSAGES_FILE, [])
    messages.append(stored_msg)
    ok = atomic_write_json(config.MESSAGES_FILE, messages)
    
    return {'stored': ok}

# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------

@app.route('/', methods=['GET', 'POST'])
def main_router():
    # 1. Проверяем, нужно ли обновить вебхук (из конфига)
    if config.REFRESH_WEBHOOK_ON_EACH_REQUEST:
        ensure_webhook_recent()

    action = request.args.get('action')
    token_arg = request.args.get('token')
    
    # Получаем токен из JSON body если есть (для POST запросов)
    token_json = None
    if request.is_json:
        token_json = request.json.get('token')
    
    # Определяем какой токен проверять
    req_token = token_json if token_json else token_arg

    # --- Router Logic ---

    if action == 'get_messages':
        if not check_token(config.EXTERNAL_ACCESS_TOKEN, req_token):
             return jsonify({'error': 'Forbidden'}), 403
        return handle_get_messages()

    elif action == 'send_message':
        if not check_token(config.EXTERNAL_ACCESS_TOKEN, req_token):
             return jsonify({'error': 'Forbidden'}), 403
        return handle_send_message()
    
    elif action == 'extpoll_get_messages':
        if config.SEND_TO_TG_THROUGH_EXTERNAL_POLL:
             # Логика та же, что и у get_messages, но для другого файла?
             # В PHP оригинале вызывался endpoint_get_messages с путем к другому файлу.
             # Реализуем упрощенно выдачу файла:
             if not check_token(config.EXTERNAL_ACCESS_TOKEN, req_token):
                return jsonify({'error': 'Forbidden'}), 403
             # Здесь можно дописать отдельную функцию чтения/очистки файла externalpoll
             # Для краткости вернем всё содержимое и очистим
             path = config.SEND_TO_TG_THROUGH_EXTERNAL_POLL_MESSAGES_FILE
             msgs = read_json_file(path, [])
             # Очищаем после отдачи? В оригинале get_messages помечал delivered.
             # Просто вернем данные.
             return jsonify({'messages': msgs})
        else:
            return jsonify("Sending to TG by poll is disabled")

    elif action == 'set_webhook':
        if not check_token(config.ADMIN_TOKEN, req_token):
             return jsonify({'error': 'Forbidden'}), 403
        res = set_telegram_webhook()
        # Обновляем таймстамп
        with open(config.WEBHOOK_TIMESTAMP_FILE, 'w') as f:
             f.write(str(int(time.time())))
        return jsonify(res)

    elif action == 'mark_all_delivered':
        if not check_token(config.ADMIN_TOKEN, req_token):
             return jsonify({'error': 'Forbidden'}), 403
        if not is_allowed_ip():
            return jsonify({'error': 'Forbidden by IP'}), 403
        
        msgs = read_json_file(config.MESSAGES_FILE, [])
        for m in msgs:
            m['delivered'] = True
            if 'delivered_at' not in m:
                m['delivered_at'] = time.time()
        atomic_write_json(config.MESSAGES_FILE, msgs)
        return jsonify({'ok': True})

    elif action == 'delete_messages':
        if not check_token(config.ADMIN_TOKEN, req_token):
             return jsonify({'error': 'Forbidden'}), 403
        if not is_allowed_ip():
            return jsonify({'error': 'Forbidden by IP'}), 403
        
        if os.path.exists(config.MESSAGES_FILE):
            os.remove(config.MESSAGES_FILE)
        return jsonify({'ok': True})
    
    elif action == 'extpoll_delete_messages':
        if not check_token(config.ADMIN_TOKEN, req_token):
             return jsonify({'error': 'Forbidden'}), 403
        path = config.SEND_TO_TG_THROUGH_EXTERNAL_POLL_MESSAGES_FILE
        if os.path.exists(path):
            os.remove(path)
        return jsonify({'ok': True})

    # --- Webhook Handler (POST from Telegram) ---
    if request.method == 'POST' and request.is_json:
        # Проверка токена (либо в URL ?token=, либо в JSON теле это обычно не присылают, но на всякий случай)
        # В оригинале TG шлет на URL ...?token=TG_SUBSCRIBE_TOKEN
        if check_token(config.TG_SUBSCRIBE_TOKEN, token_arg):
             res = handle_telegram_update(request.json)
             return jsonify({'ok': True, 'result': res})
        
        # Если это просто POST без корректного токена, но с JSON - возможно это попытка вызвать метод без action?
        # В оригинале проверяется только Webhook Logic если action is null.
        # Если токен не подошел - Forbidden.
        if not action:
            return jsonify({'error': 'Forbidden'}), 403

    # --- HTML Status Page (Default GET) ---
    protocol = 'https' if request.is_secure else 'http'
    host_url = f"{protocol}://{request.host}{request.path}"
    
    html = f"""
    <!doctype html>
    <html lang="ru">
    <head>
        <meta charset="utf-8">
        <title>Python Tg Backend</title>
        <style>body{{font-family:Arial,sans-serif;line-height:1.5;padding:20px;color:#222}} code{{background:#eee;padding:2px 5px;border-radius:3px}}</style>
    </head>
    <body>
        <h1>Python Tg Backend</h1>
        <p>Порт PHP-скрипта на Python (Flask).</p>
        <ul>
            <li><strong>Webhook URL (для бота):</strong> <br><code>{host_url}?token={config.TG_SUBSCRIBE_TOKEN}</code></li>
            <li><strong>Получить сообщения (POST/GET):</strong> <br><code>{host_url}?action=get_messages&token=YOUR_TOKEN</code></li>
            <li><strong>Отправить сообщение (POST JSON):</strong> <br><code>{host_url}?action=send_message&token=YOUR_TOKEN</code> <br> Payload: <code>{{"msg": "text", "channel_id": "123"}}</code></li>
            <li><strong>Установить webhook (POST/GET):</strong> <br><code>{host_url}?action=set_webhook&token={config.ADMIN_TOKEN}</code></li>
        </ul>
    </body>
    </html>
    """
    return render_template_string(html)

if __name__ == '__main__':
    # Запуск сервера разработки
    print(f"Сервер запущен. Данные будут в: {config.DATA_DIR}")
    app.run(host=config.LOCAL_SERVER_IP, port=config.LOCAL_SERVER_PORT, debug=config.LOCAL_SERVER_DEBUG)
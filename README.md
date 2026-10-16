# bot_bet

Отправка оповещений в Telegram из командной строки и из Python. Только стандартная
библиотека и `curl`; SOCKS-прокси поддерживается через `TELEGRAM_PROXY`.

## Настройка

```bash
cp .env.example .env     # заполнить TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID
python3 -m bot_bet check # проверит токен и подскажет рабочий chat_id
```

## Использование

```bash
python3 -m bot_bet send "текст оповещения"
echo "текст" | python3 -m bot_bet send -
```

```python
from bot_bet import telegram
telegram.send_message(telegram.config_from_env(), "текст")
```

Токен хранится только в `.env` (в Git не попадает) и не выводится ни в журнал, ни в ошибки.
Длинный текст режется на сообщения по 4096 символов.

## Тесты

```bash
python3 -m unittest discover -s tests
```

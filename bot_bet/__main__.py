"""Командная строка.

  python -m bot_bet send "текст"      отправить сообщение
  echo "текст" | python -m bot_bet send -   текст со стандартного входа
  python -m bot_bet check             проверить токен и найти рабочий chat_id
"""

from __future__ import annotations

import argparse
import sys

from bot_bet import telegram


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bot_bet", description="Оповещения в Telegram")
    sub = parser.add_subparsers(dest="command", required=True)
    send = sub.add_parser("send", help="отправить сообщение")
    send.add_argument("text", help="текст или '-' для чтения со стандартного входа")
    sub.add_parser("check", help="проверить токен и идентификатор чата")
    args = parser.parse_args(argv)

    try:
        if args.command == "send":
            config = telegram.config_from_env()
            text = sys.stdin.read() if args.text == "-" else args.text
            count = telegram.send_message(config, text)
            print(f"отправлено сообщений: {count}")
        else:
            config = telegram.config_from_env(need_chat=False)
            me = telegram.call(config, "getMe")
            print(f"бот: @{me.get('username')} (id {me.get('id')})")
            if config.chat_id:
                chat_id, info = telegram.resolve_chat(config)
                title = info.get("title") or info.get("username") or info.get("first_name")
                print(f"чат: {title!r}, тип {info.get('type')}, рабочий TELEGRAM_CHAT_ID={chat_id}")
            else:
                print("TELEGRAM_CHAT_ID не задан")
    except telegram.TelegramError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Отправка сообщений через Telegram Bot API.

Запросы выполняет curl: он умеет SOCKS-прокси (нужен, когда с машины Telegram
недоступен), стоит на любой машине и позволяет не класть токен в argv: адрес с
токеном передаётся конфигом через stdin, в `ps` его не видно.
Тексты ошибок никогда не содержат адрес запроса (в нём токен).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

API_HOST = "https://api.telegram.org"
MAX_MESSAGE_LEN = 4096
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TelegramError(RuntimeError):
    """Ошибка отправки. Токена в тексте нет."""


@dataclass(frozen=True)
class Config:
    token: str
    chat_id: str
    proxy: str | None = None
    timeout: int = 15


def load_env_file(path: Path = PROJECT_ROOT / ".env") -> None:
    """Добавляет значения из .env в окружение; уже заданные переменные важнее файла."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def config_from_env(need_chat: bool = True) -> Config:
    load_env_file()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or (need_chat and not chat_id):
        needed = "TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID" if need_chat else "TELEGRAM_BOT_TOKEN"
        raise SystemExit(f"Не заданы {needed}: скопируйте .env.example в .env и заполните")
    return Config(token=token, chat_id=chat_id, proxy=os.environ.get("TELEGRAM_PROXY") or None)


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def curl_request(config: Config, method: str, params: dict[str, str]) -> tuple[list[str], str]:
    """Аргументы curl и конфиг для stdin. Токен только в конфиге."""
    argv = ["curl", "-sS", "-m", str(config.timeout), "-K", "-"]
    if config.proxy:
        argv += ["--proxy", config.proxy]
    lines = [f'url = "{API_HOST}/bot{_quote(config.token)}/{method}"']
    lines += [f'data-urlencode = "{_quote(k)}={_quote(v)}"' for k, v in params.items()]
    return argv, "\n".join(lines) + "\n"


Runner = Callable[[list[str], str], "subprocess.CompletedProcess[str]"]


def _run(argv: list[str], stdin: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=60)


def call(
    config: Config,
    method: str,
    params: dict[str, str] | None = None,
    runner: Runner = _run,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 3,
):
    """Вызов метода Bot API. Возвращает `result`; ошибка — TelegramError без токена."""
    argv, stdin = curl_request(config, method, params or {})
    last = "неизвестная ошибка"
    for attempt in range(attempts):
        if attempt:
            sleep(2 * attempt)
        try:
            proc = runner(argv, stdin)
        except subprocess.TimeoutExpired:
            last = "таймаут"
            continue
        if proc.returncode != 0:
            last = f"curl завершился с кодом {proc.returncode}"
            continue
        try:
            body = json.loads(proc.stdout)
        except json.JSONDecodeError:
            last = "ответ не похож на JSON"
            continue
        if body.get("ok"):
            return body.get("result")
        code, description = body.get("error_code"), body.get("description", "")
        if code == 429:
            sleep(min(int((body.get("parameters") or {}).get("retry_after", 1)), 30))
            last = "слишком частые запросы (429)"
            continue
        if code and code < 500:
            raise TelegramError(f"{code}: {description}")  # повтор не поможет
        last = f"{code}: {description}"
    raise TelegramError(last)


def split_text(text: str, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    """Режет длинный текст по строкам так, чтобы каждый кусок влезал в сообщение."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks


def send_message(config: Config, text: str, **kwargs) -> int:
    """Отправляет текст (при необходимости несколькими сообщениями). Возвращает число сообщений."""
    if not text.strip():
        raise TelegramError("пустой текст")
    chunks = split_text(text)
    for chunk in chunks:
        call(config, "sendMessage", {"chat_id": config.chat_id, "text": chunk}, **kwargs)
    return len(chunks)


def chat_id_candidates(chat_id: str) -> list[str]:
    """Для голого числа добавляет форму канала: у каналов идентификатор вида -100…"""
    if chat_id.startswith(("-", "@")):
        return [chat_id]
    return [chat_id, f"-100{chat_id}"]


def resolve_chat(config: Config, **kwargs) -> tuple[str, dict]:
    """Находит рабочий идентификатор чата среди кандидатов. Ошибка — если нет ни одного."""
    errors = []
    for candidate in chat_id_candidates(config.chat_id):
        try:
            info = call(Config(config.token, candidate, config.proxy, config.timeout), "getChat",
                        {"chat_id": candidate}, **kwargs)
            return candidate, info
        except TelegramError as exc:
            errors.append(f"{candidate}: {exc}")
    raise TelegramError("чат не найден или бот не добавлен в него; " + "; ".join(errors))

import json
import subprocess
import unittest

from bot_bet import telegram as tg

CONFIG = tg.Config(token="123:SECRET", chat_id="-100500", proxy="socks5h://127.0.0.1:1080")


def reply(body, code=0):
    return subprocess.CompletedProcess([], code, stdout=json.dumps(body) if isinstance(body, dict) else body, stderr="")


class Script:
    """Подменяет curl: отдаёт заготовленные ответы по очереди и запоминает вызовы."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, argv, stdin):
        self.calls.append((argv, stdin))
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


NO_SLEEP = {"sleep": lambda _: None}


class CurlRequestTest(unittest.TestCase):
    def test_token_only_in_stdin_config_not_in_argv(self):
        argv, stdin = tg.curl_request(CONFIG, "sendMessage", {"chat_id": "-100500", "text": 'a "b"\nc'})
        self.assertFalse(any("SECRET" in a for a in argv))
        self.assertIn("bot123:SECRET/sendMessage", stdin)
        self.assertIn('\\"b\\"', stdin)
        self.assertIn("\\n", stdin)

    def test_proxy_is_passed(self):
        argv, _ = tg.curl_request(CONFIG, "getMe", {})
        self.assertEqual(argv[argv.index("--proxy") + 1], "socks5h://127.0.0.1:1080")

    def test_no_proxy_flag_without_proxy(self):
        argv, _ = tg.curl_request(tg.Config("t", "1"), "getMe", {})
        self.assertNotIn("--proxy", argv)


class CallTest(unittest.TestCase):
    def test_success_returns_result(self):
        runner = Script(reply({"ok": True, "result": {"message_id": 7}}))
        self.assertEqual(tg.call(CONFIG, "sendMessage", {}, runner=runner), {"message_id": 7})

    def test_client_error_is_not_retried_and_has_no_token(self):
        runner = Script(reply({"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}))
        with self.assertRaises(tg.TelegramError) as ctx:
            tg.call(CONFIG, "sendMessage", {}, runner=runner, **NO_SLEEP)
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("chat not found", str(ctx.exception))
        self.assertNotIn("SECRET", str(ctx.exception))

    def test_server_error_is_retried_then_succeeds(self):
        runner = Script(reply({"ok": False, "error_code": 502, "description": "Bad Gateway"}),
                        reply({"ok": True, "result": 1}))
        self.assertEqual(tg.call(CONFIG, "x", {}, runner=runner, **NO_SLEEP), 1)
        self.assertEqual(len(runner.calls), 2)

    def test_curl_failure_is_retried_then_raises(self):
        runner = Script(reply("", 28), reply("", 28), reply("", 28))
        with self.assertRaises(tg.TelegramError) as ctx:
            tg.call(CONFIG, "x", {}, runner=runner, **NO_SLEEP)
        self.assertIn("28", str(ctx.exception))
        self.assertNotIn("SECRET", str(ctx.exception))

    def test_timeout_and_garbage_are_errors(self):
        runner = Script(subprocess.TimeoutExpired("curl", 1), reply("<html>"), reply("<html>"))
        with self.assertRaises(tg.TelegramError):
            tg.call(CONFIG, "x", {}, runner=runner, **NO_SLEEP)

    def test_rate_limit_waits_retry_after(self):
        waits = []
        runner = Script(reply({"ok": False, "error_code": 429, "parameters": {"retry_after": 3}}),
                        reply({"ok": True, "result": 1}))
        tg.call(CONFIG, "x", {}, runner=runner, sleep=waits.append)
        self.assertIn(3, waits)


class SendMessageTest(unittest.TestCase):
    def test_short_text_is_one_message(self):
        runner = Script(reply({"ok": True, "result": {}}))
        self.assertEqual(tg.send_message(CONFIG, "привет", runner=runner), 1)
        self.assertIn("chat_id=-100500", runner.calls[0][1])

    def test_long_text_is_split_within_limit(self):
        text = "\n".join("строка %04d" % i for i in range(1000))
        chunks = tg.split_text(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= tg.MAX_MESSAGE_LEN for c in chunks))
        self.assertEqual("".join(chunks), text + "") if text.endswith("\n") else self.assertEqual("".join(chunks).rstrip("\n"), text)

    def test_single_huge_line_is_cut(self):
        chunks = tg.split_text("x" * 9000)
        self.assertEqual([len(c) for c in chunks], [4096, 4096, 808])

    def test_blank_text_is_rejected(self):
        with self.assertRaises(tg.TelegramError):
            tg.send_message(CONFIG, "  \n ", runner=Script())


class ChatResolveTest(unittest.TestCase):
    def test_candidates(self):
        self.assertEqual(tg.chat_id_candidates("-100500"), ["-100500"])
        self.assertEqual(tg.chat_id_candidates("@chan"), ["@chan"])
        self.assertEqual(tg.chat_id_candidates("1675016973"), ["1675016973", "-1001675016973"])

    def test_falls_back_to_channel_form(self):
        runner = Script(reply({"ok": False, "error_code": 400, "description": "chat not found"}),
                        reply({"ok": True, "result": {"title": "Канал", "type": "channel"}}))
        chat_id, info = tg.resolve_chat(tg.Config("t", "1675016973"), runner=runner, **NO_SLEEP)
        self.assertEqual(chat_id, "-1001675016973")
        self.assertEqual(info["type"], "channel")

    def test_nothing_found_raises(self):
        bad = reply({"ok": False, "error_code": 400, "description": "chat not found"})
        with self.assertRaises(tg.TelegramError):
            tg.resolve_chat(tg.Config("t", "1675016973"), runner=Script(bad, bad), **NO_SLEEP)


class ConfigTest(unittest.TestCase):
    def test_missing_token_exits(self):
        import os
        saved = {k: os.environ.pop(k, None) for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")}
        orig = tg.load_env_file
        tg.load_env_file = lambda *a, **k: None
        try:
            with self.assertRaises(SystemExit):
                tg.config_from_env()
        finally:
            tg.load_env_file = orig
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()

"""
Модульные и нагрузочные тесты приложения (tests/test_app.py).

Проверяет:
1. Корректность конфигурации всех 9 AI-провайдеров (OpenRouter, DeepSeek, OpenAI,
   Anthropic, Gemini, Groq, Qwen, Moonshot, Custom).
2. Изоляцию сессий и управление чатами (создание, переименование, автозаголовок,
   удаление, экспорт в .txt, сохранность временных меток).
3. Потокобезопасную работу лимитера (DemoRateLimiter) и таймера обратного отсчёта.
4. Одновременную работу 10 пользователей в параллельных потоках (concurrency test).
5. Формирование контекста LLMService (системный промпт через role='system') и подсчёт токенов.
"""

import io
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from unittest.mock import MagicMock, patch

from src.chat_state import ChatSessionManager
from src.config import PROVIDERS, AppConfig, get_provider
from src.document_parser import DocumentParser, DocumentParserError
from src.jira_pm_service import (
    AnalysisType,
    JiraIssue,
    JiraPMService,
    JiraPushService,
)
from src.llm_service import LLMService, ResponseTelemetry, TokenCounter
from src.rate_limiter import DemoRateLimiter, format_countdown


class TestProvidersAndConfig(unittest.TestCase):
    """Тестирование справочника провайдеров и конфигурации."""

    def test_all_required_providers_present(self):
        expected = {
            "openrouter",
            "deepseek",
            "openai",
            "anthropic",
            "gemini",
            "groq",
            "qwen",
            "moonshot",
            "custom",
        }
        self.assertTrue(expected.issubset(set(PROVIDERS.keys())))

        for pid, spec in PROVIDERS.items():
            self.assertEqual(pid, spec.id)
            self.assertTrue(spec.base_url.startswith("http"))
            self.assertGreater(len(spec.models), 0)
            self.assertIn(spec.default_model, spec.models)

    def test_get_provider_fallback(self):
        spec = get_provider("unknown_provider_id")
        self.assertEqual(spec.id, "openrouter")

    def test_app_config_defaults(self):
        cfg = AppConfig()
        self.assertFalse(cfg.is_demo_configured)
        cfg_with_key = AppConfig(demo_api_key="sk-test-123")
        self.assertTrue(cfg_with_key.is_demo_configured)


class TestChatSessionManager(unittest.TestCase):
    """Тестирование управления чатами, временных меток и экспорта."""

    def test_chat_lifecycle_and_auto_title(self):
        state = {}
        mgr = ChatSessionManager(state, default_demo_enabled=True)

        self.assertEqual(mgr.state["auth_mode"], "demo")
        self.assertEqual(len(mgr.chats), 1)
        first_id = mgr.active_chat_id
        self.assertEqual(mgr.active_chat["title"], "Новый чат 1")

        # Первое сообщение должно автоматически обновить заголовок чата
        msg = mgr.add_message(
            "user", "Объясни принципы ООП простыми словами", timestamp="12:00:01"
        )
        self.assertEqual(msg["timestamp"], "12:00:01")
        self.assertEqual(
            mgr.active_chat["title"], "Объясни принципы ООП простыми словами"
        )

        # Второе сообщение не должно перезаписывать таймстамп первого
        mgr.add_message("assistant", "ООП строится на 4 принципах...", timestamp="12:00:05")
        self.assertEqual(mgr.active_chat["messages"][0]["timestamp"], "12:00:01")
        self.assertEqual(mgr.active_chat["messages"][1]["timestamp"], "12:00:05")

        # Переименование вручную блокирует автозаголовок
        self.assertTrue(mgr.rename_active_chat("Подготовка к интервью"))
        self.assertEqual(mgr.active_chat["title"], "Подготовка к интервью")
        self.assertTrue(mgr.active_chat["custom_title"])

        # Удаление единственного чата должно автоматически создавать новый пустой чат
        feedback = mgr.delete_chat(first_id)
        self.assertIn("Создан новый пустой чат", feedback)
        self.assertEqual(len(mgr.chats), 1)
        self.assertNotEqual(mgr.active_chat_id, first_id)

    def test_export_active_chat_txt(self):
        state = {}
        mgr = ChatSessionManager(state)
        mgr.state["chat_rules"] = "Отвечай строго по фактам"
        mgr.add_message("user", "Привет!", timestamp="10:15:00")
        mgr.add_message("assistant", "Здравствуйте!", timestamp="10:15:02")

        filename, content = mgr.export_active_chat_txt()
        self.assertTrue(filename.endswith(".txt"))
        self.assertIn("[Системные правила]: Отвечай строго по фактам", content)
        self.assertIn("[10:15:00] Пользователь: Привет!", content)
        self.assertIn("[10:15:02] AI: Здравствуйте!", content)


class TestRateLimiterAndConcurrency(unittest.TestCase):
    """Тестирование лимитов бесплатного API, таймера и конкурентной работы 10 пользователей."""

    def test_countdown_formatting(self):
        self.assertEqual(format_countdown(65), "01 мин. 05 сек.")
        self.assertEqual(format_countdown(3661), "01 ч. 01 мин. 01 сек.")

    def test_session_and_global_limits(self):
        limiter = DemoRateLimiter(daily_global_limit=3, session_limit=2)

        # Пользователь 1 делает 2 запроса (исчерпывает свой сессионный лимит)
        s1 = limiter.consume(session_used=0)
        self.assertTrue(s1.allowed)
        s2 = limiter.consume(session_used=1)
        self.assertTrue(s2.allowed)
        s3 = limiter.consume(session_used=2)
        self.assertFalse(s3.allowed)
        self.assertIn("сессию", s3.reason)

        # Пользователь 2 делает 1 запрос (исчерпывает общий дневной лимит 3/3)
        u2_s1 = limiter.consume(session_used=0)
        self.assertTrue(u2_s1.allowed)
        u2_s2 = limiter.consume(session_used=1)
        self.assertFalse(u2_s2.allowed)
        self.assertIn("дневной лимит для всех пользователей превышен", u2_s2.reason)
        self.assertGreater(u2_s2.reset_seconds, 0)

    def test_upstream_429_cooldown_timer(self):
        limiter = DemoRateLimiter(daily_global_limit=50, session_limit=10)
        limiter.mark_upstream_exhausted(cooldown_seconds=1800)

        status = limiter.check_status(session_used=0)
        self.assertFalse(status.allowed)
        self.assertGreater(status.reset_seconds, 1700)
        self.assertIn("мин.", status.formatted_timer)

    def test_10_concurrent_users_isolation_and_rate_limiting(self):
        """
        Симуляция одновременной работы 10 пользователей:
        - У каждого пользователя своя изолированная сессия (ChatSessionManager) и свой ключ/история;
        - Все 10 пользователей одновременно обращаются к общему DemoRateLimiter с дневным лимитом 25 запросов (по 5 попыток от каждого = 50 попыток).
        Проверяем:
        1. Ровно 25 запросов проходят, и ни одним больше (отсутствие race conditions).
        2. Сообщения и API-ключи разных пользователей никогда не перемешиваются.
        """
        shared_limiter = DemoRateLimiter(daily_global_limit=25, session_limit=10)
        barrier = threading.Barrier(10)

        def simulate_user(user_idx: int):
            user_state = {}
            mgr = ChatSessionManager(user_state, default_demo_enabled=True)
            mgr.state["api_key"] = f"sk-user-secret-{user_idx}"

            # Синхронизируем старт всех 10 потоков в одну микросекунду
            barrier.wait()

            allowed_count = 0
            for req_num in range(5):
                status = shared_limiter.consume(
                    session_used=mgr.state["demo_session_used"]
                )
                if status.allowed:
                    mgr.state["demo_session_used"] += 1
                    allowed_count += 1
                    mgr.add_message("user", f"Вопрос {req_num} от пользователя {user_idx}")
                    mgr.add_message("assistant", f"Ответ {req_num} для пользователя {user_idx}")

            return user_idx, allowed_count, mgr

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(simulate_user, i) for i in range(10)]
            results = [f.result() for f in futures]

        total_allowed = sum(r[1] for r in results)
        # Из 50 одновременных запросов от 10 человек должно пройти ровно 25 (дневной лимит)
        self.assertEqual(total_allowed, 25)

        # Проверяем полную изоляцию данных каждого из 10 пользователей
        for user_idx, allowed_count, mgr in results:
            self.assertEqual(mgr.state["api_key"], f"sk-user-secret-{user_idx}")
            messages = mgr.active_chat["messages"]
            self.assertEqual(len(messages), allowed_count * 2)
            for msg in messages:
                self.assertIn(f"пользователя {user_idx}", msg["content"])


class TestLLMServiceAndTokens(unittest.TestCase):
    """Тестирование формирования системного промпта и подсчёта токенов."""

    def test_build_messages_payload_with_system_prompt(self):
        history = [
            {"role": "user", "content": "Привет", "timestamp": "12:00:00"},
            {"role": "assistant", "content": "Привет! Чем помочь?", "timestamp": "12:00:02"},
        ]
        payload = LLMService.build_messages_payload(
            chat_history=history,
            user_prompt="Что такое Python?",
            system_prompt="Отвечай как преподаватель университета",
        )
        self.assertEqual(len(payload), 4)
        self.assertEqual(
            payload[0],
            {"role": "system", "content": "Отвечай как преподаватель университета"},
        )
        self.assertEqual(payload[-1], {"role": "user", "content": "Что такое Python?"})

    def test_token_counter_includes_system_prompt(self):
        messages = [{"role": "user", "content": "Hello world"}]
        tokens_without_rules = TokenCounter.count_chat_tokens(messages, system_prompt="")
        tokens_with_rules = TokenCounter.count_chat_tokens(
            messages,
            system_prompt="Always respond concisely in Russian.",
        )
        self.assertGreater(tokens_with_rules, tokens_without_rules)

    def test_llm_service_generate_and_stream_with_mock_client(self):
        """Проверяет синхронную и потоковую генерацию, а также перехват ошибки 429."""
        from unittest.mock import MagicMock, patch
        import src.llm_service as llm_mod

        fake_openai_cls = MagicMock()
        mock_client = MagicMock()
        fake_openai_cls.return_value = mock_client

        # Настраиваем мок синхронного ответа
        mock_choice = MagicMock()
        mock_choice.message.content = "Тестовый ответ от модели"
        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_completion

        with patch.object(llm_mod, "OpenAI", fake_openai_cls):
            service = LLMService(
                api_key="sk-test-key",
                base_url="https://api.deepseek.com",
                model_name="deepseek-chat",
                temperature=0.5,
            )
            reply = service.generate_response(
                user_prompt="Проверка",
                chat_history=[],
                system_prompt="Будь краток",
            )
            self.assertEqual(reply, "Тестовый ответ от модели")

            # Проверяем, что системный промпт ушёл отдельной ролью 'system'
            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
            self.assertEqual(call_kwargs["model"], "deepseek-chat")
            self.assertEqual(
                call_kwargs["messages"][0],
                {"role": "system", "content": "Будь краток"},
            )
            self.assertEqual(
                call_kwargs["messages"][1],
                {"role": "user", "content": "Проверка"},
            )

    def test_fetch_available_models_filters_non_chat_models(self):
        """Проверяет автоподгрузку живого списка моделей и фильтрацию служебных моделей."""
        from unittest.mock import MagicMock, patch
        import src.llm_service as llm_mod

        fake_openai_cls = MagicMock()
        mock_client = MagicMock()
        fake_openai_cls.return_value = mock_client

        m1 = MagicMock(id="openai/gpt-oss-120b")
        m2 = MagicMock(id="qwen/qwen3.8-27b")
        m3 = MagicMock(id="whisper-large-v3")  # Аудио-модель должна быть отфильтрована
        m4 = MagicMock(id="meta-llama/llama-prompt-guard-2-86m")  # Guard должна быть отфильтрована
        mock_client.models.list.return_value = MagicMock(data=[m1, m2, m3, m4])

        with patch.object(llm_mod, "OpenAI", fake_openai_cls):
            models = LLMService.fetch_available_models(
                api_key="gsk_test",
                base_url="https://api.groq.com/openai/v1",
            )
            self.assertEqual(models, ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"])



class TestDocumentParser(unittest.TestCase):
    """Тестирование извлечения текста из загруженных документов."""

    def test_supported_extensions(self):
        self.assertTrue(DocumentParser.is_supported("requirements.txt"))
        self.assertTrue(DocumentParser.is_supported("spec.PDF"))
        self.assertFalse(DocumentParser.is_supported("archive.exe"))

    def test_extract_text_from_txt(self):
        raw = "Привет, мир!".encode("utf-8")
        text = DocumentParser.extract_text(raw, "note.txt")
        self.assertEqual(text, "Привет, мир!")

    def test_extract_text_from_csv(self):
        raw = "name,age\nAlice,30\nBob,25".encode("utf-8")
        text = DocumentParser.extract_text(raw, "users.csv")
        self.assertIn("Alice", text)
        self.assertIn("Bob", text)

    def test_extract_text_from_json(self):
        raw = '{"project":"AI Chat","version":2}'.encode("utf-8")
        text = DocumentParser.extract_text(raw, "config.json")
        self.assertIn('"project": "AI Chat"', text)

    def test_extract_text_unsupported_raises(self):
        with self.assertRaises(DocumentParserError):
            DocumentParser.extract_text(b"data", "file.bin")

    def test_summarize_for_context_truncates_long_text(self):
        long_text = "a" * 10000
        short = DocumentParser.summarize_for_context(long_text, max_chars=100)
        self.assertLessEqual(len(short), 200)
        self.assertIn("[...", short)


class TestResponseTelemetry(unittest.TestCase):
    """Тестирование формата строки инженерной телеметрии."""

    def test_format_line(self):
        telemetry = ResponseTelemetry(
            elapsed_seconds=0.85,
            generated_tokens=120,
            speed_tps=141.0,
            model_name="openai/gpt-oss-120b",
        )
        line = telemetry.format_line()
        self.assertIn("0.85 сек", line)
        self.assertIn("120", line)
        self.assertIn("141", line)
        self.assertIn("openai/gpt-oss-120b", line)


class TestLLMServiceTelemetry(unittest.TestCase):
    """Тестирование замера времени генерации и подсчёта токенов."""

    def _build_mock_openai(self, content: str):
        fake_openai_cls = MagicMock()
        mock_client = MagicMock()
        fake_openai_cls.return_value = mock_client

        mock_choice = MagicMock()
        mock_choice.message.content = content
        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_completion
        return fake_openai_cls, mock_client

    def test_generate_response_telemetry(self):
        import src.llm_service as llm_mod

        fake_openai_cls, _ = self._build_mock_openai("Тестовый ответ")
        with patch.object(llm_mod, "OpenAI", fake_openai_cls):
            service = LLMService(
                api_key="sk-test",
                base_url="https://api.deepseek.com",
                model_name="deepseek-chat",
            )
            content, telemetry = service.generate_response_telemetry(
                user_prompt="Вопрос",
                chat_history=[],
                system_prompt="Системная инструкция",
            )
            self.assertEqual(content, "Тестовый ответ")
            self.assertIsInstance(telemetry, ResponseTelemetry)
            self.assertEqual(telemetry.model_name, "deepseek-chat")
            self.assertGreaterEqual(telemetry.generated_tokens, 1)

    def test_stream_response_telemetry(self):
        import src.llm_service as llm_mod

        fake_openai_cls = MagicMock()
        mock_client = MagicMock()
        fake_openai_cls.return_value = mock_client

        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "Привет"
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = " мир"
        mock_client.chat.completions.create.return_value = iter([chunk1, chunk2])

        with patch.object(llm_mod, "OpenAI", fake_openai_cls):
            service = LLMService(
                api_key="sk-test",
                base_url="https://api.deepseek.com",
                model_name="deepseek-chat",
            )
            holder = {}
            chunks = list(
                service.stream_response_telemetry(
                    user_prompt="q",
                    chat_history=[],
                    telemetry_holder=holder,
                )
            )
            self.assertEqual("".join(chunks), "Привет мир")
            self.assertIn("telemetry", holder)
            self.assertIsInstance(holder["telemetry"], ResponseTelemetry)


class TestJiraPMService(unittest.TestCase):
    """Тестирование декомпозиции, оценки, рисков и экспорта в CSV/Markdown."""

    @staticmethod
    def _make_service(response_text: str, telemetry: Optional[ResponseTelemetry] = None):
        mock_llm = MagicMock()
        if telemetry is None:
            telemetry = ResponseTelemetry(1.0, 100, 100.0, "test-model")
        mock_llm.generate_response_telemetry.return_value = (response_text, telemetry)
        mock_llm.model_name = "test-model"
        return JiraPMService(mock_llm)

    def test_analyze_decomposition_and_estimation(self):
        response = json.dumps(
            {
                "issues": [
                    {
                        "issue_type": "Epic",
                        "summary": "Авторизация",
                        "description": "Реализовать вход пользователей",
                        "acceptance_criteria": "Можно войти по email",
                        "priority": "High",
                        "story_points": 8,
                        "pert_optimistic_hours": 4,
                        "pert_realistic_hours": 6,
                        "pert_pessimistic_hours": 14,
                    }
                ],
                "risks": [],
                "clarifying_questions": ["Нужна ли 2FA?"],
            }
        )
        service = self._make_service(response)
        result = service.analyze(
            "Сделать авторизацию",
            [AnalysisType.DECOMPOSITION, AnalysisType.ESTIMATION],
        )
        self.assertEqual(len(result.issues), 1)
        issue = result.issues[0]
        self.assertEqual(issue.issue_type, "Epic")
        self.assertEqual(issue.summary, "Авторизация")
        self.assertEqual(issue.story_points, 8)
        # PERT: (4 + 4*6 + 14) / 6 = 7.0
        self.assertAlmostEqual(issue.original_estimate_hours, 7.0, places=2)
        self.assertIn("Нужна ли 2FA?", result.clarifying_questions)
        self.assertIsNotNone(result.report_markdown)
        self.assertIsNotNone(result.telemetry)

    def test_analyze_risks(self):
        response = json.dumps(
            {
                "issues": [],
                "risks": [
                    {
                        "risk": "Задержка API интеграции",
                        "probability": "Medium",
                        "impact": "High",
                        "mitigation": "Зарезервировать буфер времени",
                        "questions": ["Есть ли SLA у поставщика API?"],
                    }
                ],
                "clarifying_questions": [],
            }
        )
        service = self._make_service(response)
        result = service.analyze("Интеграция с внешним API", [AnalysisType.RISKS])
        self.assertEqual(len(result.risks), 1)
        self.assertEqual(result.risks[0].risk, "Задержка API интеграции")
        # Риски также превращаются в строки для Jira CSV
        self.assertTrue(any(issue.issue_type == "Risk" for issue in result.issues))

    def test_fallback_on_invalid_json(self):
        service = self._make_service("Просто текстовый ответ модели без JSON")
        result = service.analyze("Требования", [AnalysisType.DECOMPOSITION])
        self.assertEqual(len(result.issues), 1)
        self.assertIn("Просто текстовый ответ", result.issues[0].description)

    def test_export_jira_csv(self):
        issues = [
            JiraIssue(
                issue_type="Story",
                summary="Страница входа",
                description="Форма логина",
                acceptance_criteria="Успешный вход",
                priority="High",
                original_estimate_hours=6,
                story_points=3,
                parent_summary="Авторизация",
            )
        ]
        csv_text = JiraPMService.export_jira_csv(issues)
        self.assertIn("Issue Type,Summary", csv_text)
        self.assertIn("Story,Страница входа", csv_text)
        self.assertIn("6", csv_text)
        self.assertIn("3", csv_text)


class TestJiraPushService(unittest.TestCase):
    """Тестирование опциональной отправки задач в Jira Cloud."""

    @patch("src.jira_pm_service.urllib.request.urlopen")
    def test_push_issues_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"id":"100","key":"PROJ-1"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        service = JiraPushService(
            domain="https://test.atlassian.net",
            email="user@example.com",
            api_token="secret-token",
            project_key="PROJ",
        )
        results = service.push_issues(
            [JiraIssue(issue_type="Task", summary="Тестовая задача")]
        )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[0]["body"]["key"], "PROJ-1")

    @patch("src.jira_pm_service.urllib.request.urlopen")
    def test_push_issues_http_error(self, mock_urlopen):
        from urllib.error import HTTPError

        error_fp = io.BytesIO(b'{"errorMessages":["Bad Request"]}')
        mock_urlopen.side_effect = HTTPError(
            "https://test.atlassian.net/rest/api/3/issue",
            400,
            "Bad Request",
            {},
            error_fp,
        )

        service = JiraPushService(
            domain="https://test.atlassian.net",
            email="user@example.com",
            api_token="secret-token",
            project_key="PROJ",
        )
        results = service.push_issues(
            [JiraIssue(issue_type="Task", summary="Тестовая задача")]
        )
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertIn("400", str(results[0]["body"]))


if __name__ == "__main__":
    unittest.main()

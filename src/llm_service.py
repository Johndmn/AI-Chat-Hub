"""
Сервисный слой работы с языковыми моделями и токенизацией (src/llm_service.py).

Отвечает за:
1. Подключение к любому OpenAI-совместимому провайдеру (OpenAI, DeepSeek,
   OpenRouter, Anthropic, Google Gemini, Groq, Qwen, Moonshot, Custom) через единый клиент.
2. Формирование корректного контекста диалога с системным промптом (role="system").
3. Потоковую (streaming) и синхронную генерацию ответов.
4. Перехват ошибок лимитов (HTTP 429 RateLimitError) и авторизации (HTTP 401/403).
5. Точный подсчёт токенов диалога и системных правил через библиотеку tiktoken.
"""

import logging
import time
from dataclasses import dataclass
from typing import Dict, Generator, List, Optional, Tuple

try:
    import tiktoken
except ImportError:
    tiktoken = None  # type: ignore
try:
    from openai import (
        APIConnectionError,
        APIStatusError,
        AuthenticationError,
        OpenAI,
        RateLimitError,
    )
except ImportError:
    OpenAI = None  # type: ignore
    APIConnectionError = Exception  # type: ignore
    APIStatusError = Exception  # type: ignore
    AuthenticationError = Exception  # type: ignore
    RateLimitError = Exception  # type: ignore

logger = logging.getLogger(__name__)


class ProviderRateLimitError(Exception):
    """
    Исключение, выбрасываемое при превышении лимитов запросов у провайдера (HTTP 429).
    Позволяет приложению включить таймер ожидания в бесплатном демо-режиме.
    """


class ProviderClientError(Exception):
    """Понятная пользователю ошибка при обращении к API провайдера."""


@dataclass(frozen=True)
class ResponseTelemetry:
    """
    Инженерная телеметрия одного ответа модели.

    Используется UI для отображения метрик производительности:
    - elapsed_seconds — реальное время генерации (time.perf_counter);
    - generated_tokens — количество токенов в ответе;
    - speed_tps — приблизительная скорость генерации, токенов в секунду;
    - model_name — имя модели, которая сгенерировала ответ.
    """

    elapsed_seconds: float
    generated_tokens: int
    speed_tps: float
    model_name: str

    def format_line(self) -> str:
        """Форматирует телеметрию в компактную строку для вывода под ответом."""
        return (
            f"⏱️ Время: {self.elapsed_seconds:.2f} сек | "
            f"⚡ Скорость: ~{self.speed_tps:.0f} ток/сек | "
            f"🔢 Токены ответа: {self.generated_tokens} | "
            f"🤖 Модель: {self.model_name}"
        )


class TokenCounter:
    """
    Утилитарный класс для подсчёта количества токенов в сообщениях и системном промпте.
    """

    DEFAULT_ENCODING = "cl100k_base"

    @classmethod
    def count_text_tokens(cls, text: str, model: str = "gpt-4o-mini") -> int:
        """Подсчитывает количество токенов в одной строке текста."""
        if not text:
            return 0
        if tiktoken is not None:
            try:
                encoding = tiktoken.encoding_for_model(model)
                return len(encoding.encode(text))
            except Exception:
                try:
                    # Для моделей DeepSeek, Claude, Gemini, Llama используется совместимая база cl100k_base
                    encoding = tiktoken.get_encoding(cls.DEFAULT_ENCODING)
                    return len(encoding.encode(text))
                except Exception:
                    pass
        # Безопасный fallback (если нет сети для скачивания словаря tiktoken или пакет не установлен)
        return max(1, len(text) // 4)

    @classmethod
    def count_chat_tokens(
        cls,
        messages: List[Dict[str, str]],
        system_prompt: str = "",
        model: str = "gpt-4o-mini",
    ) -> int:
        """
        Вычисляет суммарное количество токенов во всей истории чата
        вместе с активными правилами общения (system_prompt).
        """
        total = 0
        if system_prompt and system_prompt.strip():
            total += cls.count_text_tokens(system_prompt.strip(), model) + 4

        for message in messages:
            content = message.get("content", "")
            # +4 служебных токена на каждое сообщение по спецификации ChatML
            total += cls.count_text_tokens(content, model) + 4

        return total


class LLMService:
    """
    Клиентский сервис для взаимодействия с LLM-провайдерами по стандарту OpenAI SDK.

    Экземпляр класса не хранит состояние чужих сессий (stateless относительно истории чатов),
    поэтому безопасен при одновременной работе множества пользователей.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model_name: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ):
        if not api_key or not api_key.strip():
            raise ValueError("API ключ не может быть пустым.")

        self.api_key = api_key.strip()
        self.base_url = base_url.strip() if base_url else "https://api.openai.com/v1"
        self.model_name = model_name.strip()
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)

        # Дополнительные заголовки для корректной работы агрегатора OpenRouter
        default_headers = {}
        if "openrouter.ai" in self.base_url:
            default_headers = {
                "HTTP-Referer": "https://streamlit.io",
                "X-Title": "AI-Chat-Hub-BYOK",
            }

        if OpenAI is None:
            raise RuntimeError(
                "Библиотека 'openai' не установлена. Выполните: pip install -r requirements.txt"
            )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            default_headers=default_headers or None,
            timeout=60.0,
        )

    @staticmethod
    def fetch_available_models(api_key: str, base_url: str) -> List[str]:
        """
        Запрашивает у API провайдера актуальный («живой») список доступных моделей
        для данного ключа через стандартный эндпоинт GET /models (client.models.list()).

        Автоматически отфильтровывает служебные не-чатовые модели (аудио whisper,
        tts, эмбеддинги, модерацию), чтобы в списке оставались только текстовые/чат модели.
        """
        if not api_key or not api_key.strip() or OpenAI is None:
            return []

        excluded_keywords = (
            "whisper",
            "tts",
            "embedding",
            "moderation",
            "guard",
            "orpheus",
            "dall-e",
            "davinci",
            "babbage",
            "canary",
        )

        try:
            client = OpenAI(
                api_key=api_key.strip(),
                base_url=base_url.strip(),
                timeout=10.0,
            )
            response = client.models.list()
            models: List[str] = []
            for item in getattr(response, "data", []):
                model_id = getattr(item, "id", "")
                if not model_id:
                    continue
                lower_id = model_id.lower()
                if any(kw in lower_id for kw in excluded_keywords):
                    continue
                models.append(model_id)

            # Сортируем список для удобства поиска
            return sorted(set(models))
        except Exception as exc:
            logger.warning("Не удалось получить живой список моделей: %s", exc)
            return []

    @staticmethod
    def build_messages_payload(
        chat_history: List[Dict[str, str]],
        user_prompt: str,
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """
        Собирает массив сообщений для отправки в API.
        В отличие от старой версии, системные правила передаются через штатную
        роль `system`, а не склеиваются с текстом пользователя.
        """
        payload: List[Dict[str, str]] = []

        if system_prompt and system_prompt.strip():
            payload.append({"role": "system", "content": system_prompt.strip()})

        for msg in chat_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant", "system") and content:
                payload.append({"role": role, "content": content})

        if user_prompt and user_prompt.strip():
            payload.append({"role": "user", "content": user_prompt.strip()})

        return payload

    def generate_response(
        self,
        user_prompt: str,
        chat_history: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Синхронно запрашивает полный ответ у модели и возвращает готовую строку.
        """
        if not user_prompt or not user_prompt.strip():
            raise ValueError("Сообщение пользователя не может быть пустым.")

        messages = self.build_messages_payload(
            chat_history=chat_history,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            content = response.choices[0].message.content
            return content or ""

        except RateLimitError as exc:
            logger.warning("Превышен лимит запросов у провайдера (429): %s", exc)
            raise ProviderRateLimitError(
                "Превышен лимит запросов (Rate Limit 429) у выбранного провайдера."
            ) from exc
        except AuthenticationError as exc:
            logger.warning("Ошибка авторизации ключа API: %s", exc)
            raise ProviderClientError(
                "Неверный или неактивный API-ключ. Проверьте ключ и выбранного провайдера."
            ) from exc
        except APIConnectionError as exc:
            logger.error("Ошибка соединения с сервером API: %s", exc)
            raise ProviderClientError(
                "Не удалось подключиться к серверу провайдера. Проверьте Base URL и интернет."
            ) from exc
        except APIStatusError as exc:
            logger.error("Ошибка статуса API (%s): %s", exc.status_code, exc)
            raise ProviderClientError(
                f"Ошибка API провайдера (код {exc.status_code}): {exc.message}"
            ) from exc
        except Exception as exc:
            logger.error("Непредвиденная ошибка при генерации ответа: %s", exc)
            raise ProviderClientError(f"Ошибка при обращении к модели: {exc}") from exc

    def generate_response_telemetry(
        self,
        user_prompt: str,
        chat_history: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> Tuple[str, ResponseTelemetry]:
        """
        Синхронная генерация ответа с замером реального времени и токенов.

        Возвращает готовый текст ответа и объект ResponseTelemetry,
        который UI показывает под сообщением.
        """
        start_time = time.perf_counter()
        content = self.generate_response(
            user_prompt=user_prompt,
            chat_history=chat_history,
            system_prompt=system_prompt,
        )
        elapsed = time.perf_counter() - start_time
        generated_tokens = TokenCounter.count_text_tokens(content, model=self.model_name)
        speed = generated_tokens / elapsed if elapsed > 0 else 0.0

        telemetry = ResponseTelemetry(
            elapsed_seconds=elapsed,
            generated_tokens=generated_tokens,
            speed_tps=speed,
            model_name=self.model_name,
        )
        return content, telemetry

    def stream_response(
        self,
        user_prompt: str,
        chat_history: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Генератор потокового ответа (Streaming) для плавного отображения текста в UI
        в реальном времени без искусственных задержек time.sleep().
        """
        if not user_prompt or not user_prompt.strip():
            raise ValueError("Сообщение пользователя не может быть пустым.")

        messages = self.build_messages_payload(
            chat_history=chat_history,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
        )

        try:
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except RateLimitError as exc:
            logger.warning("Превышен лимит запросов у провайдера (429): %s", exc)
            raise ProviderRateLimitError(
                "Превышен лимит запросов (Rate Limit 429) у выбранного провайдера."
            ) from exc
        except AuthenticationError as exc:
            logger.warning("Ошибка авторизации ключа API: %s", exc)
            raise ProviderClientError(
                "Неверный или неактивный API-ключ. Проверьте ключ и выбранного провайдера."
            ) from exc
        except APIConnectionError as exc:
            logger.error("Ошибка соединения с сервером API: %s", exc)
            raise ProviderClientError(
                "Не удалось подключиться к серверу провайдера. Проверьте Base URL и интернет."
            ) from exc
        except APIStatusError as exc:
            logger.error("Ошибка статуса API (%s): %s", exc.status_code, exc)
            raise ProviderClientError(
                f"Ошибка API провайдера (код {exc.status_code}): {exc.message}"
            ) from exc
        except Exception as exc:
            logger.error("Непредвиденная ошибка при потоковой генерации: %s", exc)
            raise ProviderClientError(f"Ошибка при обращении к модели: {exc}") from exc

    def stream_response_telemetry(
        self,
        user_prompt: str,
        chat_history: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        telemetry_holder: Optional[Dict] = None,
    ) -> Generator[str, None, None]:
        """
        Потоковая генерация с замером времени и подсчётом токенов.

        Args:
            telemetry_holder: изменяемый словарь, в который метод запишет
                объект ResponseTelemetry после завершения генерации
                (или при возникновении ошибки). UI передаёт пустой dict
                и читает telemetry_holder["telemetry"] после write_stream.
        """
        start_time = time.perf_counter()
        collected_chunks: List[str] = []

        try:
            for chunk in self.stream_response(
                user_prompt=user_prompt,
                chat_history=chat_history,
                system_prompt=system_prompt,
            ):
                collected_chunks.append(chunk)
                yield chunk
        finally:
            full_content = "".join(collected_chunks)
            elapsed = time.perf_counter() - start_time
            generated_tokens = TokenCounter.count_text_tokens(
                full_content, model=self.model_name
            )
            speed = generated_tokens / elapsed if elapsed > 0 else 0.0

            telemetry = ResponseTelemetry(
                elapsed_seconds=elapsed,
                generated_tokens=generated_tokens,
                speed_tps=speed,
                model_name=self.model_name,
            )
            if telemetry_holder is not None:
                telemetry_holder["telemetry"] = telemetry

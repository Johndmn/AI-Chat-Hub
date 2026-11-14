"""
Модуль конфигурации приложения (src/config.py).

Отвечает за:
1. Хранение спецификаций поддерживаемых AI-провайдеров (OpenAI, DeepSeek,
   OpenRouter, Anthropic Claude, Google Gemini, Groq, Qwen, Moonshot Kimi и Custom).
2. Загрузку настроек бесплатного Демо-режима из переменных окружения (.env)
   или секретов Streamlit Cloud (st.secrets).
3. Хранение шаблонов быстрых промптов.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # Встроенный парсер .env на случай, если пакет python-dotenv ещё не установлен
    _env_path = Path(".env")
    if _env_path.exists():
        for _line in _env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class ProviderSpec:
    """
    Неизменяемая структура данных (Value Object), описывающая одного AI-провайдера.
    Все перечисленные провайдеры поддерживают единый протокол OpenAI SDK через base_url.
    """

    id: str
    name: str
    base_url: str
    models: List[str]
    default_model: str
    key_placeholder: str
    docs_url: str
    description: str


# Справочник поддерживаемых провайдеров для режима BYOK (Bring Your Own Key)
PROVIDERS: Dict[str, ProviderSpec] = {
    "openrouter": ProviderSpec(
        id="openrouter",
        name="🌐 OpenRouter (Все модели + Free)",
        base_url="https://openrouter.ai/api/v1",
        models=[
            "deepseek/deepseek-chat-v3-0324:free",
            "google/gemini-2.0-flash-exp:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "qwen/qwen-2.5-72b-instruct:free",
            "anthropic/claude-3.7-sonnet",
            "anthropic/claude-3.5-haiku",
            "openai/gpt-4o-mini",
            "google/gemini-2.5-pro-preview",
        ],
        default_model="deepseek/deepseek-chat-v3-0324:free",
        key_placeholder="sk-or-v1-...",
        docs_url="https://openrouter.ai/keys",
        description=(
            "Единый агрегатор для сотней моделей (Claude, Gemini, DeepSeek, GPT, Llama). "
            "Модели с суффиксом :free доступны бесплатно."
        ),
    ),
    "deepseek": ProviderSpec(
        id="deepseek",
        name="🐋 DeepSeek (Китай — V3 / R1)",
        base_url="https://api.deepseek.com",
        models=[
            "deepseek-chat",
            "deepseek-reasoner",
        ],
        default_model="deepseek-chat",
        key_placeholder="sk-...",
        docs_url="https://platform.deepseek.com/api_keys",
        description=(
            "Официальный API DeepSeek. deepseek-chat (V3) — быстрый и дешёвый, "
            "deepseek-reasoner (R1) — для сложной логики и кода."
        ),
    ),
    "openai": ProviderSpec(
        id="openai",
        name="🤖 OpenAI (GPT-4o / GPT-4.1)",
        base_url="https://api.openai.com/v1",
        models=[
            "gpt-4o-mini",
            "gpt-4o",
            "gpt-4-turbo",
            "gpt-3.5-turbo",
        ],
        default_model="gpt-4o-mini",
        key_placeholder="sk-proj-...",
        docs_url="https://platform.openai.com/api-keys",
        description="Официальный API OpenAI. Требует положительного баланса на аккаунте.",
    ),
    "anthropic": ProviderSpec(
        id="anthropic",
        name="🧠 Anthropic (Claude 3.7 / 3.5)",
        base_url="https://api.anthropic.com/v1/",
        models=[
            "claude-3-7-sonnet-latest",
            "claude-3-5-sonnet-latest",
            "claude-3-5-haiku-latest",
        ],
        default_model="claude-3-7-sonnet-latest",
        key_placeholder="sk-ant-...",
        docs_url="https://console.anthropic.com/settings/keys",
        description="Официальный OpenAI-совместимый эндпоинт Anthropic Claude.",
    ),
    "gemini": ProviderSpec(
        id="gemini",
        name="✨ Google Gemini (2.5 / 2.0 Flash)",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        models=[
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-pro",
        ],
        default_model="gemini-2.0-flash",
        key_placeholder="AIzaSy...",
        docs_url="https://aistudio.google.com/app/apikey",
        description=(
            "Официальный API Google AI Studio. Имеет щедрый бесплатный тариф (Free Tier)."
        ),
    ),
    "groq": ProviderSpec(
        id="groq",
        name="⚡ Groq (Сверхбыстрый LPU + Free Tier)",
        base_url="https://api.groq.com/openai/v1",
        models=[
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "qwen/qwen3.8-27b",
            "allam-2-7b",
        ],
        default_model="openai/gpt-oss-120b",
        key_placeholder="gsk_...",
        docs_url="https://console.groq.com/keys",
        description=(
            "Сверхбыстрый инференс открытых моделей (GPT-OSS 120B, Qwen 3.8 27B). "
            "Бесплатный ключ выдаётся без банковской карты."
        ),
    ),
    "qwen": ProviderSpec(
        id="qwen",
        name="🐉 Qwen / Alibaba Cloud (Китай)",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        models=[
            "qwen-plus",
            "qwen-max",
            "qwen-turbo",
            "qwen2.5-coder-32b-instruct",
        ],
        default_model="qwen-plus",
        key_placeholder="sk-...",
        docs_url="https://modelstudio.console.alibabacloud.com/",
        description="Официальный API Alibaba Cloud Model Studio (DashScope) для моделей Qwen.",
    ),
    "moonshot": ProviderSpec(
        id="moonshot",
        name="🌙 Moonshot / Kimi (Китай)",
        base_url="https://api.moonshot.ai/v1",
        models=[
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
        ],
        default_model="moonshot-v1-8k",
        key_placeholder="sk-...",
        docs_url="https://platform.moonshot.ai/",
        description="Китайский провайдер Moonshot AI (модели Kimi с большим контекстом).",
    ),
    "custom": ProviderSpec(
        id="custom",
        name="🛠️ Свой OpenAI-совместимый сервер (Custom)",
        base_url="http://localhost:11434/v1",
        models=["llama3", "mistral", "custom-model"],
        default_model="custom-model",
        key_placeholder="any-key-or-ollama",
        docs_url="https://platform.openai.com/docs/api-reference",
        description="Подключение любого локального (Ollama, vLLM, LM Studio) или корпоративного сервера.",
    ),
}

# Готовые шаблоны для блока «Быстрые промпты» в боковой панели
PROMPT_TEMPLATES: Dict[str, Dict[str, str]] = {
    "essay": {
        "icon": "✍️",
        "title": "Написать эссе",
        "text": "Напиши подробное и структурированное эссе на тему: ",
    },
    "explain": {
        "icon": "🔍",
        "title": "Объяснить код",
        "text": "Объясни подробно по шагам следующий код и укажи возможные ошибки:\n```\n[вставь код здесь]\n```",
    },
    "summarize": {
        "icon": "📝",
        "title": "Резюмировать",
        "text": "Кратко выдели главные мысли и выводы из следующего текста:\n",
    },
}


def _read_secret_or_env(key: str, default: str = "") -> str:
    """
    Безопасно читает переменную сначала из os.environ (.env),
    затем из st.secrets (если приложение запущено в Streamlit Cloud).
    """
    env_val = os.getenv(key)
    if env_val is not None and env_val.strip() != "":
        return env_val.strip()

    try:
        import streamlit as st

        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass

    return default


@dataclass
class AppConfig:
    """
    Конфигурация приложения и встроенного бесплатного Демо-режима.

    Если владелец приложения задал DEMO_API_KEY (в .env или Streamlit Secrets),
    посетители могут сразу тестировать чат без ввода своего ключа в пределах
    установленных дневных и сессионных лимитов.
    """

    demo_api_key: str = field(default="")
    demo_base_url: str = field(default="https://openrouter.ai/api/v1")
    demo_model_name: str = field(default="deepseek/deepseek-chat-v3-0324:free")
    demo_provider_label: str = field(default="OpenRouter / Groq Free Demo")
    demo_daily_global_limit: int = field(default=100)
    demo_session_limit: int = field(default=15)
    default_temperature: float = field(default=0.7)

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Фабричный метод для загрузки конфигурации из окружения."""
        try:
            from dotenv import load_dotenv

            load_dotenv(override=True)
        except ImportError:
            pass

        # Поддерживаем как новую переменную DEMO_API_KEY, так и старую OPENAI_API_KEY
        raw_key = _read_secret_or_env("DEMO_API_KEY") or _read_secret_or_env(
            "OPENAI_API_KEY"
        )
        # Отфильтровываем тестовые заглушки (placeholder)
        if raw_key.startswith("your_") or raw_key == "sk-proj-your-key-here":
            raw_key = ""

        base_url = _read_secret_or_env("DEMO_BASE_URL", "")
        model_name = _read_secret_or_env("DEMO_MODEL_NAME", "")

        # Умное автоопределение провайдера по префиксу ключа (защита от опечаток в конфиге):
        # Если введён ключ Groq (gsk_...), автоматически ставим URL и актуальную модель Groq
        if raw_key.startswith("gsk_"):
            if not base_url or "openrouter.ai" in base_url:
                base_url = "https://api.groq.com/openai/v1"
            if (
                not model_name
                or ":" in model_name
                or model_name == "llama-3.3-70b-versatile"
            ):
                model_name = "openai/gpt-oss-120b"
        elif raw_key.startswith("AIza"):
            if not base_url:
                base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
            if not model_name:
                model_name = "gemini-2.0-flash"
        else:
            if not base_url:
                base_url = "https://openrouter.ai/api/v1"
            if not model_name:
                model_name = "deepseek/deepseek-chat-v3-0324:free"
        provider_label = _read_secret_or_env(
            "DEMO_PROVIDER_LABEL", "Бесплатный Демо API"
        )

        try:
            daily_limit = int(_read_secret_or_env("DEMO_DAILY_GLOBAL_LIMIT", "100"))
        except ValueError:
            daily_limit = 100

        try:
            session_limit = int(_read_secret_or_env("DEMO_SESSION_LIMIT", "15"))
        except ValueError:
            session_limit = 15

        try:
            temperature = float(_read_secret_or_env("OPENAI_TEMPERATURE", "0.7"))
        except ValueError:
            temperature = 0.7

        return cls(
            demo_api_key=raw_key,
            demo_base_url=base_url,
            demo_model_name=model_name,
            demo_provider_label=provider_label,
            demo_daily_global_limit=max(1, daily_limit),
            demo_session_limit=max(1, session_limit),
            default_temperature=min(max(0.0, temperature), 1.0),
        )

    @property
    def is_demo_configured(self) -> bool:
        """Проверяет, задан ли серверный ключ для бесплатного демо-режима."""
        return bool(self.demo_api_key)


def get_provider(provider_id: str) -> ProviderSpec:
    """Возвращает спецификацию провайдера по его ID (или OpenRouter по умолчанию)."""
    return PROVIDERS.get(provider_id, PROVIDERS["openrouter"])

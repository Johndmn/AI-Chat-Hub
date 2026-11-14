# Архитектура проекта AI Chat Hub (Multi-Provider BYOK, Free Demo & PM Copilot)

Документ описывает устройство системы, зоны ответственности каждого файла, объектно-ориентированную модель (ООП), работу с конкурентными пользователями (5–10+ человек одновременно) и сценарии развёртывания.

---

## 1. Дерево проекта и ответственность файлов

```text
AI-Chat-Hub/
├── app.py                  # Слой представления (Presentation Layer / Streamlit UI)
├── src/                    # Бизнес-логика и доменные сервисы (Application & Domain Layer)
│   ├── __init__.py         # Экспорт публичного интерфейса пакета src
│   ├── config.py           # Конфигурация приложения, реестр 9 AI-провайдеров и шаблоны
│   ├── rate_limiter.py     # Потокобезопасный лимитер и таймер обратного отсчёта для Демо-режима
│   ├── llm_service.py      # Клиентский сервис обращения к LLM (streaming/sync), телеметрия и подсчёт токенов
│   ├── chat_state.py       # Управление сессией пользователя, историей чатов и экспортом в .txt
│   ├── document_parser.py  # [Beta] Извлечение текста из файлов ТЗ (.txt/.md/.csv/.json, опционально .pdf)
│   └── jira_pm_service.py  # [Beta] Декомпозиция, PERT-оценка, аудит рисков, экспорт в CSV/Markdown, push в Jira
├── tests/                  # Автоматические модульные и нагрузочные тесты
│   └── test_app.py         # 28 тестов: провайдеры, чаты, токены, таймер, 10 потоков, парсер документов, Jira PM
├── requirements.txt        # Зависимости проекта (streamlit, openai, tiktoken, python-dotenv)
├── .env.example            # Шаблон переменных окружения для бесплатного демо-режима
├── pyproject.toml          # Настройки форматирования (black, isort)
├── .flake8                 # Настройки линтера flake8
├── ARCHITECTURE.md         # Архитектурная документация
└── README.md               # Инструкция по быстрому старту и деплою
```

---

## 2. Принципы ООП и Чистого Кода (Clean Architecture)

Проект разделён по принципу **Single Responsibility Principle (SRP — Принцип единственной ответственности)** и **Dependency Inversion (Инверсия зависимостей)**:

### 2.1. `src/config.py` — Конфигурация и спецификации (`ProviderSpec`, `AppConfig`)
- **`ProviderSpec` (`@dataclass(frozen=True)`)** — неизменяемый объект-значение (Value Object), хранящий параметры подключения к конкретному провайдеру: `id`, `name`, `base_url`, список моделей `models`, `default_model` и ссылку на получение ключа `docs_url`.
- **Реестр `PROVIDERS`** включает 9 провайдеров, работающих по единому стандарту OpenAI-совместимого API:
  1. **OpenRouter** (`https://openrouter.ai/api/v1`) — бесплатные (`:free`) и платные модели всех мировых вендоров.
  2. **DeepSeek** (`https://api.deepseek.com`) — китайские модели `deepseek-chat` (V3) и `deepseek-reasoner` (R1).
  3. **OpenAI** (`https://api.openai.com/v1`) — `gpt-4o-mini`, `gpt-4o`, `gpt-4-turbo`, `gpt-3.5-turbo`.
  4. **Anthropic Claude** (`https://api.anthropic.com/v1/`) — `claude-3-7-sonnet-latest`, `claude-3-5-sonnet-latest`, `claude-3-5-haiku-latest`.
  5. **Google Gemini** (`https://generativelanguage.googleapis.com/v1beta/openai/`) — `gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-1.5-pro`.
  6. **Groq** (`https://api.groq.com/openai/v1`) — скоростной инференс `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` и др.
  7. **Qwen / Alibaba Cloud DashScope** (`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`) — `qwen-plus`, `qwen-max`, `qwen-turbo`.
  8. **Moonshot / Kimi** (`https://api.moonshot.ai/v1`) — `moonshot-v1-8k`, `moonshot-v1-32k`, `moonshot-v1-128k`.
  9. **Custom Server** — подключение любого локального (`Ollama`, `vLLM`, `LM Studio`) или корпоративного шлюза.
- **`AppConfig`** — отвечает за чтение настроек бесплатного демо-ключа (`DEMO_API_KEY`, `DEMO_BASE_URL`, `DEMO_MODEL_NAME`, суточные и сессионные лимиты) сначала из `.env`, а при деплое в облако — из `st.secrets`.

### 2.2. `src/rate_limiter.py` — Лимитер и таймер (`DemoRateLimiter`, `RateLimitStatus`)
- **`DemoRateLimiter`** решает проблему защиты бесплатного API-ключа при публичной демонстрации проекта.
- Использует потокобезопасный мьютекс `threading.Lock()`, поэтому при одновременных запросах от 5–10+ человек исключено состояние гонки (race condition).
- Контролирует три уровня ограничений:
  1. **Индивидуальный лимит на сессию** (`session_limit`, по умолчанию 15 сообщений).
  2. **Общий дневной лимит на всех посетителей** (`daily_global_limit`, по умолчанию 100 сообщений в сутки).
  3. **Блокировка при HTTP 429 от внешнего провайдера** (`mark_upstream_exhausted`) — если бесплатный тариф у самого провайдера (OpenRouter/Groq) исчерпан, включается глобальный таймер обратного отсчёта.
- **`RateLimitStatus`** возвращает статус проверки и отформатированный таймер (`ЧЧ ч. ММ мин. СС сек.`), который выводится в интерфейсе вместе с предложением перейти в режим BYOK.

### 2.3. `src/llm_service.py` — Сервис моделей, токенов и телеметрии (`LLMService`, `TokenCounter`, `ResponseTelemetry`)
- **`LLMService`** инкапсулирует работу с официальным клиентом `openai.OpenAI`.
- Вместо устаревшего и тяжёлого LangChain используется прямой протокол OpenAI SDK:
  - Системные правила («Правила общения») передаются штатной ролью `{"role": "system", "content": ...}`, а не склеиваются с текстом пользователя.
  - Метод `stream_response()` возвращает генератор чанков для живого потокового вывода (`st.write_stream`) без искусственных задержек `time.sleep()`.
  - Перехватывает ошибки провайдера и преобразует их в доменные исключения `ProviderRateLimitError` (код 429) и `ProviderClientError` (ошибки ключа/сети).
- **`ResponseTelemetry`** — неизменяемый dataclass, который фиксирует реальное время генерации (`time.perf_counter`), количество токенов ответа, скорость (~токенов/сек) и имя модели. Методы `generate_response_telemetry()` и `stream_response_telemetry()` возвращают/заполняют эту телеметрию, чтобы UI показывал её под каждым ответом.
- **`TokenCounter`** считает токены через `tiktoken` с учётом как истории сообщений, так и системного промпта (с автоматическим fallback при работе офлайн).

### 2.4. `src/chat_state.py` — Менеджер пользовательской сессии (`ChatSessionManager`)
- Инкапсулирует всю работу с чатами поверх любого словаря состояния (`st.session_state` в браузере или обычного `dict` в тестах).
- Отвечает за:
  - создание, переключение, переименование и удаление чатов;
  - автоматическое создание заголовка чата по первому вопросу пользователя;
  - сохранение точного времени (`HH:MM:SS`) в момент отправки каждого сообщения;
  - экспорт активного чата и системных правил в текстовый файл `.txt`;
  - хранение рабочего пространства (`workspace_mode`: `chat` / `jira`) и прикреплённого к чату файла.
- Метод `add_message()` поддерживает поле `metadata` (например, `ResponseTelemetry`), которое не попадает в текст переписки, но выводится в UI под ответом модели.

### 2.5. `src/document_parser.py` — Парсер документов (`DocumentParser`, `DocumentParserError`) [Beta]

> Статус: работает, но активно дорабатывается. Подходит для демонстрации, но не считается production-ready.
- Извлекает чистый текст из загруженных пользователем файлов: `.txt`, `.md`, `.csv`, `.json`.
- Поддерживает `.pdf`, если установлен опциональный пакет `pypdf` (`pip install pypdf`), без жёсткой зависимости в `requirements.txt`.
- Автоматически определяет кодировку текста (utf-8 → cp1251 → latin-1) и безопасно обрезает большие ТЗ для окна контекста модели (`summarize_for_context`).
- Не зависит от Streamlit: принимает `bytes` и имя файла, возвращает текст и количество токенов.

### 2.6. `src/jira_pm_service.py` — PM и Jira Copilot (`JiraPMService`, `JiraIssue`, `RiskItem`, `JiraPushService`) [Beta]

> Статус: MVP. Декомпозиция, оценка и CSV-экспорт работают. Push в Jira — базовый, требует доработки связей и обработки ошибок.
- **`JiraPMService`** принимает экземпляр `LLMService` и строит структурированные промпты для трёх видов анализа:
  - **Декомпозиция** — иерархия `Epic → Story/Task → Subtask` с `Acceptance Criteria`.
  - **PERT-оценка** — оптимистичная, реалистичная и пессимистичная оценки в часах, итоговая оценка по формуле `(O + 4R + P) / 6` и Story Points.
  - **Аудит рисков** — таблица рисков (вероятность, влияние, митигация) и уточняющие вопросы заказчику.
- Парсит ответ модели из JSON; при неудаче использует безопасный fallback (одна задача с полным текстом ответа).
- **`JiraIssue`** — dataclass строки задачи с полями, совместимыми с импортом Jira CSV.
- **`RiskItem`** — dataclass строки риска.
- Экспорт:
  - `JiraPMService.export_jira_csv()` — готовый CSV для *Issues → Import Issues from CSV*.
  - `JiraPMService.analyze().report_markdown` — человекочитаемый Markdown-отчёт.
- **`JiraPushService`** (опционально) отправляет сгенерированные задачи напрямую в Jira Cloud через REST API v3 (`POST /rest/api/3/issue`) с использованием стандартной библиотеки `urllib` (без дополнительных зависимостей).

---

## 3. Как обеспечивается одновременная работа 5–10+ пользователей

В старой версии приложения все пользователи читали и перезаписывали одну и ту же папку `data/chats/default.json` на диске сервера, из-за чего при входе двух человек их чаты перемешивались.

В новой архитектуре:
1. **Полная изоляция данных сессии (`ChatSessionManager` + `st.session_state`):**
   У каждого подключённого браузера (вкладки) в памяти процесса Streamlit создаётся свой изолированный объект `st.session_state`. API-ключи BYOK, список чатов, переписка, прикреплённые файлы и результаты Jira-анализа Пользователя №1 физически недоступны Пользователю №2.
2. **Единый потокобезопасный счётчик демо-квоты (`@st.cache_resource` + `DemoRateLimiter`):**
   Только объект `DemoRateLimiter` разделяется между всеми посетителями через декоратор `@st.cache_resource`. Доступ к счётчику внутри него защищён `threading.Lock()`. Это проверено автоматическим нагрузочным тестом `test_10_concurrent_users_isolation_and_rate_limiting` в `tests/test_app.py`.
3. **Пользовательские файлы не пишутся на диск сервера:**
   Загруженные ТЗ и результаты анализа хранятся только в `st.session_state` и выдаются через `st.download_button`. Соответствует требованию многопользовательской безопасности.

---

## 4. Развёртывание: от демонстрации на Streamlit Cloud до Production-сервера

### Вариант А: Демонстрационный деплой на Streamlit Community Cloud (бесплатно)
1. Загрузите репозиторий на GitHub.
2. Зайдите на [share.streamlit.io](https://share.streamlit.io/), выберите репозиторий и главный файл `app.py`.
3. В разделе **Advanced Settings → Secrets** укажите настройки бесплатного демо-режима:
   ```toml
   DEMO_API_KEY = "sk-or-v1-ваш-бесплатный-ключ-openrouter-или-groq"
   DEMO_BASE_URL = "https://openrouter.ai/api/v1"
   DEMO_MODEL_NAME = "deepseek/deepseek-chat-v3-0324:free"
   DEMO_DAILY_GLOBAL_LIMIT = "100"
   DEMO_SESSION_LIMIT = "15"
   ```
4. Готово: посетители смогут сразу тестировать чат и Jira & PM Copilot на бесплатном API, а при превышении лимита увидят таймер и смогут ввести свой собственный API-ключ любого из 9 провайдеров.

### Вариант Б: Production-деплой на собственном сервере (VPS / Render / AWS / Docker)
Для запуска на выделенном сервере:
```bash
pip install -r requirements.txt
# Опционально: поддержка PDF
pip install pypdf
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
```
Если в будущем потребуется превратить приложение из демо-инструмента в коммерческий SaaS с постоянными аккаунтами:
- Благодаря тому, что вся логика состояния вынесена в класс `ChatSessionManager` (`src/chat_state.py`), достаточно добавить в него методы сохранения/загрузки в PostgreSQL или Redis по `user_id` после авторизации, не переписывая `app.py` и `src/llm_service.py`.
- Логика Jira-анализа (`src/jira_pm_service.py`) также изолирована от UI и легко может быть переиспользована в фоновых Celery-задачах или backend-API.

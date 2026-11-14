"""
Главный модуль веб-интерфейса Streamlit (app.py).

Архитектурная роль файла:
Отвечает исключительно за отображение интерфейса (Presentation Layer)
и связывание действий пользователя с бизнес-логикой из пакета `src/`:
- `AppConfig` и `PROVIDERS` (src/config.py) — настройки провайдеров и демо-режима;
- `DemoRateLimiter` (src/rate_limiter.py) — общий счётчик бесплатных запросов и таймер;
- `ChatSessionManager` (src/chat_state.py) — управление чатами в сессии пользователя;
- `LLMService` и `TokenCounter` (src/llm_service.py) — запросы к моделям, автоподгрузка
  живого списка моделей (`fetch_available_models`) и подсчёт токенов.
"""

from typing import List, Optional, Tuple

import streamlit as st

from src.chat_state import ChatSessionManager
from src.config import PROMPT_TEMPLATES, PROVIDERS, AppConfig, get_provider
from src.document_parser import DocumentParser, DocumentParserError
from src.jira_pm_service import (
    AnalysisType,
    JiraIssue,
    JiraPMService,
    JiraPushService,
)
from src.llm_service import (
    LLMService,
    ProviderClientError,
    ProviderRateLimitError,
    ResponseTelemetry,
    TokenCounter,
)
from src.rate_limiter import DemoRateLimiter

# =====================================================================
# 1. Настройка страницы Streamlit
# =====================================================================

st.set_page_config(
    page_title="AI Chat Hub — Multi-Provider BYOK & Demo",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =====================================================================
# 2. Глобальные объекты сервера (общие для 5–10+ одновременных пользователей)
# =====================================================================


def get_app_config() -> AppConfig:
    """Читает актуальную конфигурацию сервера (.env / st.secrets)."""
    return AppConfig.from_env()


@st.cache_resource
def get_global_rate_limiter(daily_limit: int, session_limit: int) -> DemoRateLimiter:
    """
    Создаёт единый потокобезопасный (thread-safe) экземпляр лимитера на весь сервер.
    Все пользователи, открывшие сайт одновременно, разделяют этот счётчик.
    """
    return DemoRateLimiter(
        daily_global_limit=daily_limit,
        session_limit=session_limit,
    )


# =====================================================================
# 3. Вспомогательные функции UI и получения живого списка моделей
# =====================================================================


def inject_custom_css() -> None:
    """Добавляет аккуратные CSS-стили, адаптивные к тёмной и светлой теме."""
    st.markdown(
        """
        <style>
        /* Выравнивание кнопки удаления чата (корзины) по центру строки */
        div[data-testid="stHorizontalBlock"] > div:nth-child(2) {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }
        div[data-testid="stHorizontalBlock"] > div:nth-child(2) button {
            margin: 0 !important;
        }
        /* Плашка счётчика токенов и режима (адаптивна к тёмной и светлой теме) */
        .status-banner {
            text-align: center;
            color: inherit;
            font-size: 0.9em;
            padding: 10px 14px;
            background-color: rgba(128, 128, 128, 0.14);
            border: 1px solid rgba(128, 128, 128, 0.25);
            border-radius: 8px;
            margin-bottom: 14px;
        }
        /* Таймер исчерпания бесплатного лимита */
        .limit-timer-box {
            padding: 14px 18px;
            border-radius: 8px;
            border-left: 5px solid #e53e3e;
            background-color: rgba(229, 62, 62, 0.12);
            color: inherit;
            margin-bottom: 16px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_message(
    role: str,
    content: str,
    timestamp: str,
    telemetry: Optional[ResponseTelemetry] = None,
) -> None:
    """
    Отрисовывает одно сообщение чата с временной меткой
    и опциональной инженерной телеметрией ответа модели.
    """
    with st.chat_message(role):
        st.markdown(content)
        if telemetry:
            st.caption(telemetry.format_line())
        if timestamp:
            st.markdown(
                f"<div style='font-size:0.75em; color:#888; "
                f"text-align:right; margin-top:-8px;'>{timestamp}</div>",
                unsafe_allow_html=True,
            )


def get_models_for_provider(
    session_mgr: ChatSessionManager,
    provider_id: str,
) -> List[str]:
    """
    Возвращает список моделей для провайдера:
    если для этого провайдера уже был загружен «живой» список через API —
    возвращает его; иначе возвращает базовый список из конфига.
    """
    fetched_map = session_mgr.state.get("fetched_models", {})
    live_list = fetched_map.get(provider_id)
    if live_list:
        return live_list
    return get_provider(provider_id).models


def build_active_llm_service(
    session_mgr: ChatSessionManager,
    config: AppConfig,
    max_tokens: Optional[int] = None,
) -> Tuple[Optional[LLMService], str]:
    """
    Создаёт экземпляр LLMService в зависимости от выбранного режима:
    - 'demo': использует встроенный серверный ключ бесплатного API;
    - 'byok': использует пользовательский ключ и выбранного провайдера.

    Args:
        max_tokens: позволяет переопределить лимит токенов для задачи
                    (например, 4096 для Jira-анализа).
    """
    mode = session_mgr.state.get("auth_mode", "byok")
    temperature = float(
        session_mgr.state.get("temperature", config.default_temperature)
    )

    if mode == "demo":
        if not config.is_demo_configured:
            return None, "Демо-ключ не задан на сервере"
        active_demo_model = (
            str(session_mgr.state.get("demo_model_override", "")).strip()
            or config.demo_model_name
        )
        service = LLMService(
            api_key=config.demo_api_key,
            base_url=config.demo_base_url,
            model_name=active_demo_model,
            temperature=temperature,
            max_tokens=max_tokens or 1024,
        )
        label = f"🎁 Демо ({active_demo_model})"
        return service, label

    # Режим BYOK (собственный ключ пользователя)
    api_key = str(session_mgr.state.get("api_key", "")).strip()
    if not api_key:
        return None, "Ожидание API-ключа (BYOK)"

    provider_id = session_mgr.state.get("provider_id", "openrouter")
    provider = get_provider(provider_id)

    base_url = (
        str(session_mgr.state.get("custom_base_url", "")).strip()
        if provider_id == "custom"
        else provider.base_url
    )

    custom_model = str(session_mgr.state.get("custom_model_name", "")).strip()
    selected_model = str(session_mgr.state.get("selected_model", "")).strip()
    model_name = custom_model or selected_model or provider.default_model

    service = LLMService(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens or 2048,
    )
    label = f"🔑 {provider.name.split()[1]} ({model_name})"
    return service, label


# =====================================================================
# 4. Всплывающее модальное окно настроек API и живого списка моделей
# =====================================================================


@st.dialog("🔌 Настройки подключения, API-ключей и моделей", width="large")
def open_api_settings_dialog(
    session_mgr: ChatSessionManager,
    config: AppConfig,
) -> None:
    """
    Всплывающее модальное окно (как в современных агентских IDE вроде OpenCode)
    для управления провайдерами, API-ключами и автоподгрузкой живого списка моделей.
    """
    st.caption(
        "Здесь вы можете переключаться между бесплатным Демо-режимом и своими API-ключами "
        "(BYOK), а также загружать актуальный список моделей напрямую с сервера провайдера."
    )

    # Переключатель режима внутри модального окна
    is_byok_now = session_mgr.state.get("auth_mode") == "byok"
    use_byok = st.toggle(
        "🔑 Использовать свой API-ключ (режим BYOK)",
        value=is_byok_now,
        help="Выключено — работает встроенный бесплатный Демо API. Включено — работает ваш собственный ключ.",
    )
    session_mgr.state["auth_mode"] = "byok" if use_byok else "demo"

    st.divider()

    if not use_byok:
        st.markdown("### 🎁 Настройки Бесплатного Демо-режима")
        if not config.is_demo_configured:
            st.warning(
                "На сервере не настроен `DEMO_API_KEY`. Включите переключатель BYOK выше "
                "и введите свой ключ."
            )
            return

        st.success(f"Подключён демо-сервер: `{config.demo_base_url}`")

        # Кнопка автоподгрузки живых моделей для демо-ключа
        demo_models = session_mgr.state.get("fetched_models", {}).get(
            "__demo__",
            [
                config.demo_model_name,
                "openai/gpt-oss-120b",
                "openai/gpt-oss-20b",
                "qwen/qwen3.8-27b",
                "allam-2-7b",
            ],
        )
        # Убираем дубликаты с сохранением порядка
        demo_models = list(dict.fromkeys(demo_models))

        if st.button(
            "🔄 Проверить и обновить живой список демо-моделей с сервера",
            use_container_width=True,
        ):
            with st.spinner("Запрашиваем список доступных моделей у сервера..."):
                live_demo = LLMService.fetch_available_models(
                    api_key=config.demo_api_key,
                    base_url=config.demo_base_url,
                )
                if live_demo:
                    session_mgr.state["fetched_models"]["__demo__"] = live_demo
                    demo_models = live_demo
                    st.success(f"✅ Найдено доступных чат-моделей: {len(live_demo)}")
                else:
                    st.warning(
                        "Сервер не вернул список моделей, используем базовый список."
                    )

        current_demo_model = (
            session_mgr.state.get("demo_model_override") or config.demo_model_name
        )
        if current_demo_model not in demo_models:
            demo_models.insert(0, current_demo_model)

        chosen_demo_model = st.selectbox(
            "Выберите бесплатную модель для Демо-режима:",
            options=demo_models,
            index=demo_models.index(current_demo_model),
        )
        session_mgr.state["demo_model_override"] = chosen_demo_model

        if st.button("✅ Применить и закрыть", type="primary", use_container_width=True):
            st.rerun()
        return

    # --- Вкладка настройки своего ключа (BYOK) ---
    st.markdown("### 🔑 Подключение собственного провайдера (BYOK)")

    provider_ids = list(PROVIDERS.keys())
    current_pid = session_mgr.state.get("provider_id", "openrouter")
    if current_pid not in provider_ids:
        current_pid = "openrouter"

    chosen_pid = st.selectbox(
        "1. Выберите AI-провайдера:",
        options=provider_ids,
        index=provider_ids.index(current_pid),
        format_func=lambda pid: PROVIDERS[pid].name,
    )
    if chosen_pid != current_pid:
        session_mgr.state["provider_id"] = chosen_pid
        session_mgr.state["selected_model"] = PROVIDERS[chosen_pid].default_model

    provider = get_provider(chosen_pid)
    st.caption(f"ℹ️ {provider.description} — [Получить API-ключ ↗]({provider.docs_url})")

    if chosen_pid == "custom":
        custom_url = st.text_input(
            "Base URL совместимого сервера:",
            value=session_mgr.state.get("custom_base_url") or provider.base_url,
            placeholder="https://api.example.com/v1",
        )
        session_mgr.state["custom_base_url"] = custom_url.strip()

    active_base_url = (
        session_mgr.state.get("custom_base_url") or provider.base_url
        if chosen_pid == "custom"
        else provider.base_url
    )

    api_key_input = st.text_input(
        f"2. Введите ваш API-ключ ({provider.name.split()[1]}):",
        value=session_mgr.state.get("api_key", ""),
        type="password",
        placeholder=provider.key_placeholder,
        help="Ключ хранится исключительно в памяти вашей текущей вкладки браузера.",
    )

    # Кнопка живой автоподгрузки списка моделей по введённому ключу
    col_fetch, col_clear = st.columns([0.7, 0.3])
    with col_fetch:
        if st.button(
            "🔄 Загрузить живой список моделей по ключу",
            use_container_width=True,
            help="Отправляет запрос GET /models к выбранному провайдеру и подгружает все реально доступные вам модели.",
        ):
            if not api_key_input.strip():
                st.error("Сначала введите API-ключ в поле выше.")
            else:
                session_mgr.state["api_key"] = api_key_input.strip()
                with st.spinner(
                    f"Запрашиваем доступные модели у {provider.name.split()[1]}..."
                ):
                    live_models = LLMService.fetch_available_models(
                        api_key=api_key_input.strip(),
                        base_url=active_base_url,
                    )
                    if live_models:
                        session_mgr.state["fetched_models"][chosen_pid] = live_models
                        session_mgr.state["selected_model"] = live_models[0]
                        st.success(
                            f"✅ Успешно загружено моделей с сервера: {len(live_models)} шт."
                        )
                    else:
                        st.warning(
                            "Не удалось получить список через /models (проверьте ключ или используйте стандартный список ниже)."
                        )
    with col_clear:
        if st.button("🗑️ Сбросить ключ", use_container_width=True):
            session_mgr.state["api_key"] = ""
            st.toast("Ключ очищен")

    available_models = get_models_for_provider(session_mgr, chosen_pid)
    is_live = chosen_pid in session_mgr.state.get("fetched_models", {})

    current_selected = session_mgr.state.get("selected_model", "")
    if current_selected not in available_models:
        current_selected = available_models[0]

    model_label = (
        f"3. Выберите модель (🟢 Живой список с сервера: {len(available_models)} шт.):"
        if is_live
        else "3. Выберите модель (базовый список провайдера):"
    )
    chosen_model = st.selectbox(
        model_label,
        options=available_models,
        index=available_models.index(current_selected),
    )

    custom_model_input = st.text_input(
        "Или введите точный ID модели вручную (необязательно):",
        value=session_mgr.state.get("custom_model_name", ""),
        placeholder="Оставьте пустым, чтобы использовать модель из списка выше",
    )

    st.divider()
    if st.button("💾 Сохранить настройки и закрыть", type="primary", use_container_width=True):
        session_mgr.state["api_key"] = api_key_input.strip()
        session_mgr.state["selected_model"] = chosen_model
        session_mgr.state["custom_model_name"] = custom_model_input.strip()

        # Если ключ введён, а живой список ещё не запрашивался — пробуем подгрузить автоматически
        if (
            api_key_input.strip()
            and chosen_pid not in session_mgr.state.get("fetched_models", {})
        ):
            live_models = LLMService.fetch_available_models(
                api_key=api_key_input.strip(),
                base_url=active_base_url,
            )
            if live_models:
                session_mgr.state["fetched_models"][chosen_pid] = live_models

        st.rerun()


# =====================================================================
# 5. Отрисовка боковой панели (Сайдбар)
# =====================================================================


def render_workspace_selector(session_mgr: ChatSessionManager) -> None:
    """
    Переключатель рабочего пространства в верхней части сайдбара.
    Позволяет быстро переключаться между чатом и PM-инструментом.
    """
    options = {
        "chat": "💬 AI Чат-Ассистент",
        "jira": "📋 Jira & PM Copilot",
    }
    current = session_mgr.state.get("workspace_mode", "chat")
    if current not in options:
        current = "chat"
        session_mgr.state["workspace_mode"] = current

    selected = st.radio(
        "Рабочее пространство:",
        options=list(options.keys()),
        index=list(options.keys()).index(current),
        format_func=lambda key: options[key],
        label_visibility="collapsed",
    )
    if selected != current:
        session_mgr.state["workspace_mode"] = selected
        st.rerun()


def render_sidebar(
    session_mgr: ChatSessionManager,
    config: AppConfig,
    rate_limiter: DemoRateLimiter,
) -> None:
    """Отрисовывает компактную боковую панель с быстрым переключателем и кнопкой модального окна."""
    with st.sidebar:
        render_workspace_selector(session_mgr)
        st.title("⚙️ Управление")

        # --- БЛОК 1: Мгновенный переключатель Демо / BYOK + кнопка модального окна ---
        st.subheader("🔌 Режим API")

        def _on_toggle_mode() -> None:
            """Callback мгновенного переключения между бесплатным Демо и своим ключом BYOK."""
            new_val = st.session_state.get("sidebar_byok_toggle", False)
            session_mgr.state["auth_mode"] = "byok" if new_val else "demo"

        is_byok = session_mgr.state.get("auth_mode") == "byok"
        st.session_state["sidebar_byok_toggle"] = is_byok

        st.toggle(
            "🔑 Свой API-ключ (BYOK)",
            key="sidebar_byok_toggle",
            on_change=_on_toggle_mode,
            help="Выключено — работает бесплатный встроенный Демо API. Включено — работает ваш собственный ключ.",
        )

        # Отображаем краткий статус текущего режима
        if not is_byok:
            if config.is_demo_configured:
                status = rate_limiter.check_status(
                    session_used=int(session_mgr.state.get("demo_session_used", 0))
                )
                active_demo_model = (
                    session_mgr.state.get("demo_model_override")
                    or config.demo_model_name
                )
                if status.allowed:
                    st.success(
                        f"🎁 **Бесплатный Демо активен**\n\n"
                        f"• Модель: `{active_demo_model}`\n"
                        f"• Осталось в сессии: **{status.remaining_session}**\n"
                        f"• Дневной пул: **{status.remaining_global}**"
                    )
                else:
                    st.error(
                        f"⏳ **Лимит исчерпан**\n\n"
                        f"Сброс через: **{status.formatted_timer}**"
                    )
            else:
                st.warning("⚠️ Демо-ключ не задан. Включите тумблер BYOK выше.")
        else:
            provider = get_provider(session_mgr.state.get("provider_id", "openrouter"))
            has_key = bool(str(session_mgr.state.get("api_key", "")).strip())
            if has_key:
                st.success(f"🔑 **BYOK подключён**\n\nПровайдер: {provider.name}")
            else:
                st.warning("🔑 **Режим BYOK**\n\nКлюч ещё не введён.")

        # Кнопка вызова всплывающего окна настроек (как в агентских IDE)
        if st.button(
            "⚙️ Настроить API и модели",
            use_container_width=True,
            type="primary" if (is_byok and not session_mgr.state.get("api_key")) else "secondary",
        ):
            open_api_settings_dialog(session_mgr, config)

        st.divider()

        # --- БЛОК 2: Управление списком чатов ---
        st.subheader("💬 История чатов")

        if st.button("🆕 Новый чат", use_container_width=True):
            session_mgr.create_chat()
            st.rerun()

        feedback = session_mgr.state.pop("feedback_message", None)
        if feedback:
            st.success(feedback)

        for chat_id, chat_data in list(session_mgr.chats.items()):
            title = chat_data.get("title", "Без названия")
            msg_count = len(chat_data.get("messages", []))
            label = f"💬 {title} ({msg_count})" if msg_count else f"💬 {title}"
            is_active = chat_id == session_mgr.active_chat_id

            col_chat, col_del = st.columns([0.84, 0.16], gap="small")
            with col_chat:
                if st.button(
                    label,
                    key=f"select_{chat_id}",
                    use_container_width=True,
                    type="primary" if is_active else "secondary",
                ):
                    session_mgr.switch_chat(chat_id)
                    st.rerun()
            with col_del:
                if st.button(
                    "🗑",
                    key=f"del_{chat_id}",
                    help="Удалить этот чат",
                    use_container_width=True,
                ):
                    session_mgr.state["pending_delete"] = chat_id
                    st.rerun()

        # Подтверждение удаления чата
        pending_id = session_mgr.state.get("pending_delete")
        if pending_id and pending_id in session_mgr.chats:
            pending_title = session_mgr.chats[pending_id].get("title", pending_id)
            st.warning(f"⚠️ Удалить чат «{pending_title}»?")
            c_yes, c_no = st.columns(2)
            with c_yes:
                if st.button(
                    "✅ Да",
                    key="confirm_del_btn",
                    type="primary",
                    use_container_width=True,
                ):
                    msg = session_mgr.delete_chat(pending_id)
                    session_mgr.state["pending_delete"] = None
                    session_mgr.state["feedback_message"] = msg
                    st.rerun()
            with c_no:
                if st.button(
                    "❌ Нет",
                    key="cancel_del_btn",
                    use_container_width=True,
                ):
                    session_mgr.state["pending_delete"] = None
                    st.rerun()

        with st.expander("✏️ Переименовать и экспортировать"):
            new_title = st.text_input(
                "Название текущего чата:",
                value=session_mgr.active_chat.get("title", ""),
                max_chars=60,
            )
            if st.button("💾 Сохранить название", use_container_width=True):
                if session_mgr.rename_active_chat(new_title):
                    session_mgr.state["feedback_message"] = "✅ Название обновлено"
                    st.rerun()

            st.markdown("---")
            if session_mgr.active_chat.get("messages"):
                fname, fcontent = session_mgr.export_active_chat_txt()
                st.download_button(
                    label="📥 Скачать чат (.txt)",
                    data=fcontent,
                    file_name=fname,
                    mime="text/plain",
                    use_container_width=True,
                )
            else:
                st.caption("Добавьте сообщения, чтобы скачать историю чата.")

        st.divider()

        # --- БЛОК 3: Быстрые промпты (шаблоны) ---
        st.subheader("⚡ Быстрые промпты")
        cols = st.columns(len(PROMPT_TEMPLATES))
        for idx, (tpl_key, tpl_data) in enumerate(PROMPT_TEMPLATES.items()):
            with cols[idx]:
                if st.button(
                    tpl_data["icon"],
                    key=f"tpl_{tpl_key}",
                    help=tpl_data["title"],
                    use_container_width=True,
                ):
                    session_mgr.state["prompt_input"] = tpl_data["text"]
                    st.rerun()

        st.divider()

        # --- БЛОК 4: Правила общения (System Prompt) ---
        st.subheader("📋 Правила общения")
        rules_val = st.text_area(
            "Системные инструкции для AI:",
            value=session_mgr.state.get("chat_rules", ""),
            height=90,
            placeholder=(
                "Например:\n"
                "- Отвечай кратко и по делу\n"
                "- Приводи примеры кода на Python"
            ),
            help="Передаются модели как системный промпт (role='system') при каждом запросе.",
        )
        session_mgr.state["chat_rules"] = rules_val
        if rules_val.strip():
            st.caption("✅ Системные правила активны")
        else:
            st.caption("ℹ️ Правила не заданы")

        st.divider()

        # --- БЛОК 5: Параметры генерации (Температура) ---
        st.subheader("🎛️ Параметры модели")
        temp_val = st.slider(
            "Температура (креативность):",
            min_value=0.0,
            max_value=1.0,
            value=float(
                session_mgr.state.get("temperature", config.default_temperature)
            ),
            step=0.05,
        )
        session_mgr.state["temperature"] = temp_val

        if st.button("↩️ Сбросить температуру", use_container_width=True):
            session_mgr.state["temperature"] = config.default_temperature
            st.rerun()


# =====================================================================
# 6. Универсальные вспомогательные функции UI
# =====================================================================


def _consume_demo_quota(
    session_mgr: ChatSessionManager,
    rate_limiter: DemoRateLimiter,
) -> Tuple[bool, Optional[str]]:
    """
    Списывает одну демо-квоту, если активен демо-режим.
    Возвращает (True, None) при успехе или (False, сообщение_об_ошибке).
    """
    if session_mgr.state.get("auth_mode") != "demo":
        return True, None

    used_in_session = int(session_mgr.state.get("demo_session_used", 0))
    quota_status = rate_limiter.consume(session_used=used_in_session)
    if not quota_status.allowed:
        return (
            False,
            (
                f"⏳ **{quota_status.reason}**\n\n"
                f"Время до автоматического сброса: **{quota_status.formatted_timer}**"
            ),
        )
    session_mgr.state["demo_session_used"] = used_in_session + 1
    return True, None


def _build_prompt_with_attachment(
    cleaned_prompt: str,
    attached_fragment: str,
    file_name: str,
) -> str:
    """
    Добавляет контекст прикреплённого документа к сообщению пользователя.
    Контекст передаётся модели, но в истории чата сохраняется только сам вопрос.
    """
    return (
        f"[Прикреплён документ: {file_name}]\n\n"
        f"Содержимое документа:\n---\n{attached_fragment}\n---\n\n"
        f"Вопрос/задание пользователя:\n{cleaned_prompt}"
    )


# =====================================================================
# 7. Обработка отправки сообщения
# =====================================================================


def handle_user_submission(
    prompt_text: str,
    session_mgr: ChatSessionManager,
    llm_service: LLMService,
    rate_limiter: DemoRateLimiter,
) -> None:
    """Единый обработчик отправки сообщения пользователя."""
    cleaned_prompt = (prompt_text or "").strip()
    if not cleaned_prompt:
        return

    is_demo = session_mgr.state.get("auth_mode") == "demo"

    allowed, error_message = _consume_demo_quota(session_mgr, rate_limiter)
    if not allowed:
        st.error(error_message)
        return

    prior_history = list(session_mgr.active_chat.get("messages", []))
    system_rules = str(session_mgr.state.get("chat_rules", "")).strip()

    attached_fragment = session_mgr.state.get("attached_file_fragment", "")
    attached_name = session_mgr.state.get("attached_file_name", "")
    final_prompt = cleaned_prompt
    if attached_fragment and attached_name:
        final_prompt = _build_prompt_with_attachment(
            cleaned_prompt, attached_fragment, attached_name
        )

    user_msg = session_mgr.add_message("user", cleaned_prompt)
    render_message("user", user_msg["content"], user_msg["timestamp"])

    with st.chat_message("assistant"):
        telemetry_holder: Dict = {}
        try:
            stream_gen = llm_service.stream_response_telemetry(
                user_prompt=final_prompt,
                chat_history=prior_history,
                system_prompt=system_rules,
                telemetry_holder=telemetry_holder,
            )
            full_response = st.write_stream(stream_gen)
            if not isinstance(full_response, str):
                full_response = str(full_response or "")

            telemetry = telemetry_holder.get("telemetry")
            session_mgr.add_message(
                "assistant",
                full_response,
                metadata={"telemetry": telemetry} if telemetry else None,
            )
            st.rerun()

        except ProviderRateLimitError as exc:
            if is_demo:
                rate_limiter.mark_upstream_exhausted()
                status = rate_limiter.check_status(
                    session_used=int(session_mgr.state.get("demo_session_used", 0))
                )
                st.error(
                    f"⏳ **Бесплатный лимит на день для всех пользователей превышен!**\n\n"
                    f"Сброс лимита через: **{status.formatted_timer}**.\n"
                    f"Включите тумблер **🔑 Свой API-ключ (BYOK)** в панели слева, "
                    f"чтобы продолжить работу без ожидания."
                )
            else:
                st.error(f"⚠️ {exc}")

        except ProviderClientError as exc:
            st.error(f"❌ {exc}")


# =====================================================================
# 7. Рабочее пространство «AI Чат-Ассистент»
# =====================================================================


def _render_attached_file_info(
    session_mgr: ChatSessionManager,
    clear_key: str = "clear_attached_file",
) -> None:
    """Показывает информацию о прикреплённом файле и кнопку удаления."""
    file_name = session_mgr.state.get("attached_file_name", "")
    file_tokens = session_mgr.state.get("attached_file_tokens", 0)
    if not file_name:
        return

    col_info, col_clear = st.columns([0.8, 0.2])
    with col_info:
        st.info(f"📎 Прикреплён файл: **{file_name}** ({file_tokens} токенов)")
    with col_clear:
        if st.button("❌ Убрать файл", key=clear_key):
            session_mgr.state["attached_file_name"] = ""
            session_mgr.state["attached_file_tokens"] = 0
            session_mgr.state["attached_file_fragment"] = ""
            st.rerun()


def _parse_and_store_uploaded_file(
    session_mgr: ChatSessionManager,
    uploaded_file,
    model: str = "gpt-4o-mini",
) -> None:
    """Извлекает текст из загруженного файла и сохраняет его в сессии пользователя."""
    try:
        _, tokens, fragment = DocumentParser.prepare_context_from_upload(
            file_bytes=uploaded_file.getvalue(),
            filename=uploaded_file.name,
            model=model,
        )
        session_mgr.state["attached_file_name"] = uploaded_file.name
        session_mgr.state["attached_file_tokens"] = tokens
        session_mgr.state["attached_file_fragment"] = fragment
    except DocumentParserError as exc:
        st.error(f"❌ {exc}")
    except Exception as exc:
        st.error(f"❌ Ошибка обработки файла: {exc}")


def _render_chat_tab(
    session_mgr: ChatSessionManager,
    config: AppConfig,
    rate_limiter: DemoRateLimiter,
) -> None:
    """Вкладка обычного чата с потоковыми ответами и телеметрией."""
    llm_service, active_label = build_active_llm_service(session_mgr, config)
    active_messages = session_mgr.active_chat.get("messages", [])
    system_rules = str(session_mgr.state.get("chat_rules", "")).strip()

    model_for_tokens = llm_service.model_name if llm_service else "gpt-4o-mini"
    total_tokens = TokenCounter.count_chat_tokens(
        messages=active_messages,
        system_prompt=system_rules,
        model=model_for_tokens,
    )

    st.markdown(
        f"<div class='status-banner'>"
        f"🔌 <b>Режим:</b> {active_label} &nbsp;|&nbsp; "
        f"💬 <b>Чат:</b> {session_mgr.active_chat.get('title')} &nbsp;|&nbsp; "
        f"🔢 <b>Токены в контексте:</b> {total_tokens}"
        f"</div>",
        unsafe_allow_html=True,
    )

    if session_mgr.state.get("auth_mode") == "demo" and config.is_demo_configured:
        demo_status = rate_limiter.check_status(
            session_used=int(session_mgr.state.get("demo_session_used", 0))
        )
        if not demo_status.allowed:
            st.markdown(
                f"<div class='limit-timer-box'>"
                f"<h4>⏳ Бесплатный лимит запросов исчерпан</h4>"
                f"<p>{demo_status.reason}</p>"
                f"<p><b>До автоматического обновления лимита осталось: "
                f"<code>{demo_status.formatted_timer}</code></b></p>"
                f"</div>",
                unsafe_allow_html=True,
            )

    if llm_service is None:
        st.info(
            "👈 Для начала работы нажмите **«⚙️ Настроить API и модели»** в боковой панели "
            "или выключите тумблер BYOK, чтобы вернуться в бесплатный Демо-режим."
        )
        if st.button("⚙️ Открыть окно настроек API и моделей", type="primary"):
            open_api_settings_dialog(session_mgr, config)
        st.stop()

    for message in active_messages:
        telemetry = None
        metadata = message.get("metadata")
        if isinstance(metadata, dict):
            telemetry = metadata.get("telemetry")
        render_message(
            role=message.get("role", "user"),
            content=message.get("content", ""),
            timestamp=message.get("timestamp", ""),
            telemetry=telemetry,
        )

    # Загрузка файла рядом с полем ввода (как в современных чат-ботах)
    uploaded_file = st.file_uploader(
        "📎 Прикрепить файл",
        type=["txt", "md", "csv", "json", "pdf"],
        key="chat_file_uploader",
        label_visibility="collapsed",
    )
    if uploaded_file is not None:
        _parse_and_store_uploaded_file(session_mgr, uploaded_file, model_for_tokens)
    _render_attached_file_info(session_mgr, clear_key="clear_chat_attached_file")

    draft_template = str(session_mgr.state.get("prompt_input", ""))
    if draft_template:
        st.info("✏️ Дополните шаблон быстрого промпта и нажмите «Отправить»:")
        edited_prompt = st.text_area(
            "Текст сообщения:",
            value=draft_template,
            height=120,
        )
        col_send, col_cancel = st.columns(2)
        with col_send:
            if st.button("📤 Отправить", type="primary", use_container_width=True):
                session_mgr.state["prompt_input"] = ""
                handle_user_submission(
                    prompt_text=edited_prompt,
                    session_mgr=session_mgr,
                    llm_service=llm_service,
                    rate_limiter=rate_limiter,
                )
        with col_cancel:
            if st.button("❌ Отмена", use_container_width=True):
                session_mgr.state["prompt_input"] = ""
                st.rerun()
    else:
        user_input = st.chat_input("Введите ваше сообщение...")
        if user_input:
            handle_user_submission(
                prompt_text=user_input,
                session_mgr=session_mgr,
                llm_service=llm_service,
                rate_limiter=rate_limiter,
            )


def _infer_provider_id_from_url(base_url: str) -> str:
    """
    Определяет ID провайдера по URL, чтобы в демо-режиме сравнение моделей
    показывало именно тот список, который доступен на активном демо-сервере.
    """
    url = base_url.lower()
    if "groq.com" in url:
        return "groq"
    if "openrouter.ai" in url:
        return "openrouter"
    if "deepseek.com" in url:
        return "deepseek"
    if "anthropic.com" in url:
        return "anthropic"
    if "generativelanguage.googleapis.com" in url:
        return "gemini"
    if "dashscope" in url or "alibabacloud" in url:
        return "qwen"
    if "moonshot.ai" in url:
        return "moonshot"
    if "openai.com" in url:
        return "openai"
    return "openrouter"


def _get_models_for_active_service(
    session_mgr: ChatSessionManager,
    base_service: LLMService,
    config: AppConfig,
) -> List[str]:
    """
    Возвращает актуальный список моделей для активного API (Demo или BYOK),
    чтобы в сравнении не предлагались модели с другого сервера.
    """
    is_demo = session_mgr.state.get("auth_mode") == "demo"
    if is_demo:
        # В демо-режиме модели могли быть подгружены под ключом __demo__
        demo_models = session_mgr.state.get("fetched_models", {}).get("__demo__")
        if demo_models:
            return demo_models
        provider_id = _infer_provider_id_from_url(config.demo_base_url)
    else:
        provider_id = session_mgr.state.get("provider_id", "openrouter")
    return get_models_for_provider(session_mgr, provider_id)


def _render_model_comparison(
    session_mgr: ChatSessionManager,
    config: AppConfig,
    rate_limiter: DemoRateLimiter,
) -> None:
    """Вкладка сравнения двух выбранных моделей по одному промпту."""
    st.subheader("⚔️ Сравнение 2 моделей")
    st.caption(
        "Один промпт отправляется двум моделям. "
        "Ниже наглядно сравниваются скорость и качество ответа."
    )

    # Базовый сервис нужен для получения кредов и определения провайдера
    base_service, _ = build_active_llm_service(session_mgr, config, max_tokens=2048)
    if base_service is None:
        st.warning(
            "Для сравнения моделей сначала настройте API-ключ или включите Демо-режим."
        )
        return

    available_models = _get_models_for_active_service(
        session_mgr, base_service, config
    )
    provider = get_provider(
        _infer_provider_id_from_url(base_service.base_url)
        if session_mgr.state.get("auth_mode") == "demo"
        else session_mgr.state.get("provider_id", "openrouter")
    )

    col_a, col_b = st.columns(2)
    with col_a:
        current_model = base_service.model_name
        index_a = (
            available_models.index(current_model)
            if current_model in available_models
            else 0
        )
        model_a = st.selectbox(
            "Модель A",
            options=available_models,
            index=index_a,
            key="compare_model_a",
        )
    with col_b:
        default_b = provider.default_model
        index_b = (
            available_models.index(default_b)
            if default_b in available_models
            else 0
        )
        model_b = st.selectbox(
            "Модель B",
            options=available_models,
            index=index_b,
            key="compare_model_b",
        )

    compare_prompt = st.text_area(
        "Промпт для сравнения:",
        height=120,
        placeholder="Введите один и тот же промпт для обеих моделей...",
    )

    # Загрузка файла для сравнения (документ добавляется к промпту)
    uploaded_file = st.file_uploader(
        "📎 Прикрепить файл к сравнению",
        type=["txt", "md", "csv", "json", "pdf"],
        key="compare_file_uploader",
        label_visibility="collapsed",
    )
    if uploaded_file is not None:
        _parse_and_store_uploaded_file(
            session_mgr, uploaded_file, base_service.model_name
        )
    _render_attached_file_info(session_mgr, clear_key="clear_compare_attached_file")

    if not st.button("🚀 Запустить сравнение", type="primary"):
        return

    cleaned_prompt = compare_prompt.strip()
    if not cleaned_prompt:
        st.warning("Сначала введите промпт для сравнения.")
        return

    # Если прикреплён файл — добавляем его содержимое к промпту
    attached_fragment = session_mgr.state.get("attached_file_fragment", "")
    attached_name = session_mgr.state.get("attached_file_name", "")
    final_prompt = cleaned_prompt
    if attached_fragment and attached_name:
        final_prompt = _build_prompt_with_attachment(
            cleaned_prompt, attached_fragment, attached_name
        )

    def run_side(model_name: str, side_label: str):
        allowed, err = _consume_demo_quota(session_mgr, rate_limiter)
        if not allowed:
            return {"error": err}
        try:
            service = LLMService(
                api_key=base_service.api_key,
                base_url=base_service.base_url,
                model_name=model_name,
                temperature=base_service.temperature,
                max_tokens=2048,
            )
            content, telemetry = service.generate_response_telemetry(
                user_prompt=final_prompt,
                chat_history=[],
                system_prompt=str(session_mgr.state.get("chat_rules", "")).strip(),
            )
            return {"content": content, "telemetry": telemetry}
        except ProviderRateLimitError as exc:
            if session_mgr.state.get("auth_mode") == "demo":
                rate_limiter.mark_upstream_exhausted()
            return {"error": str(exc)}
        except ProviderClientError as exc:
            return {"error": str(exc)}

    with st.spinner("Ожидаем ответы от моделей..."):
        result_a = run_side(model_a, "A")
        result_b = run_side(model_b, "B")

    col_res_a, col_res_b = st.columns(2)
    with col_res_a:
        st.markdown(f"### 🅰️ {model_a}")
        if "error" in result_a:
            st.error(result_a["error"])
        else:
            st.markdown(result_a["content"])
            st.caption(result_a["telemetry"].format_line())
    with col_res_b:
        st.markdown(f"### 🅱️ {model_b}")
        if "error" in result_b:
            st.error(result_b["error"])
        else:
            st.markdown(result_b["content"])
            st.caption(result_b["telemetry"].format_line())


def render_chat_workspace(
    session_mgr: ChatSessionManager,
    config: AppConfig,
    rate_limiter: DemoRateLimiter,
) -> None:
    """Отрисовывает рабочее пространство универсального чата."""
    st.title("🤖 AI Chat Hub")
    st.caption(
        "Универсальный AI-ассистент: бесплатный демо-режим + поддержка BYOK "
        "(OpenRouter, DeepSeek, OpenAI, Claude, Gemini, Groq, Qwen)"
    )

    chat_tab, compare_tab = st.tabs(["💬 Чат", "⚔️ Сравнение 2 моделей"])
    with chat_tab:
        _render_chat_tab(session_mgr, config, rate_limiter)
    with compare_tab:
        _render_model_comparison(session_mgr, config, rate_limiter)


# =====================================================================
# 8. Рабочее пространство «Jira & PM Copilot»
# =====================================================================


@st.dialog("🚀 Отправка задач в Jira", width="large")
def open_jira_push_dialog(issues: List[JiraIssue]) -> None:
    """Модальное окно для отправки сгенерированных задач в реальный проект Jira."""
    st.caption(
        "Укажите параметры Jira Cloud. Задачи будут созданы через REST API v3 "
        "(/rest/api/3/issue)."
    )
    domain = st.text_input(
        "Jira Domain:",
        placeholder="https://your-domain.atlassian.net",
        help="Базовый URL вашего Jira Cloud",
    )
    email = st.text_input("Email пользователя:", placeholder="user@example.com")
    api_token = st.text_input(
        "Jira API Token:",
        type="password",
        help="Создаётся в настройках профиля Jira → Security → API tokens",
    )
    project_key = st.text_input(
        "Project Key:",
        placeholder="PROJ",
        help="Ключ проекта в Jira",
    )

    if not st.button("📤 Отправить задачи в Jira", type="primary"):
        return

    if not domain or not email or not api_token or not project_key:
        st.error("Заполните все поля для подключения к Jira.")
        return

    push_service = JiraPushService(
        domain=domain,
        email=email,
        api_token=api_token,
        project_key=project_key,
    )
    with st.spinner("Отправка задач в Jira..."):
        results = push_service.push_issues(issues)

    for result in results:
        if result.get("ok"):
            st.success(f"✅ Создано: {result['summary']}")
        else:
            st.error(f"❌ Ошибка для «{result['summary']}»: {result.get('body')}")


def render_jira_workspace(
    session_mgr: ChatSessionManager,
    config: AppConfig,
    rate_limiter: DemoRateLimiter,
) -> None:
    """Отрисовывает рабочее пространство проектного менеджера и Jira."""
    st.title("📋 Jira & PM Copilot")
    st.caption(
        "Декомпозиция требований, AI-оценка методом PERT и аудит рисков для проектных команд"
    )

    # --- Ввод требований и загрузка файла ---
    col_input, col_file = st.columns([0.7, 0.3])
    with col_input:
        requirements = st.text_area(
            "Сырые требования / описание проекта:",
            value=session_mgr.state.get("jira_requirements", ""),
            height=180,
            placeholder=(
                "Например: Создать личный кабинет клиента с авторизацией, "
                "историей заказов и уведомлениями..."
            ),
        )
    with col_file:
        uploaded = st.file_uploader(
            "📎 Загрузить ТЗ / протокол созвона",
            type=["txt", "md", "csv", "json", "pdf"],
            key="jira_file_uploader",
        )
        if uploaded is not None:
            try:
                full_text, tokens, fragment = DocumentParser.prepare_context_from_upload(
                    file_bytes=uploaded.getvalue(),
                    filename=uploaded.name,
                )
                # Автоматически дополняем поле требований содержимым файла
                current = session_mgr.state.get("jira_requirements", "")
                separator = "\n\n" if current.strip() else ""
                session_mgr.state["jira_requirements"] = (
                    current + separator + fragment
                )
                st.success(f"✅ Загружено {tokens} токенов из {uploaded.name}")
                st.rerun()
            except DocumentParserError as exc:
                st.error(f"❌ {exc}")
            except Exception as exc:
                st.error(f"❌ Ошибка обработки файла: {exc}")

    session_mgr.state["jira_requirements"] = requirements

    analysis_options = {
        AnalysisType.DECOMPOSITION: AnalysisType.label(AnalysisType.DECOMPOSITION),
        AnalysisType.ESTIMATION: AnalysisType.label(AnalysisType.ESTIMATION),
        AnalysisType.RISKS: AnalysisType.label(AnalysisType.RISKS),
    }
    selected_types = st.multiselect(
        "Выберите виды PM-анализа:",
        options=list(analysis_options.keys()),
        default=session_mgr.state.get("jira_analysis_types", list(analysis_options.keys())),
        format_func=lambda key: analysis_options[key],
    )
    session_mgr.state["jira_analysis_types"] = selected_types

    if not selected_types:
        st.info("Выберите хотя бы один вид анализа.")
        st.stop()

    run_disabled = not requirements.strip()
    if st.button(
        "🔍 Запустить AI-анализ",
        type="primary",
        disabled=run_disabled,
    ):
        allowed, err = _consume_demo_quota(session_mgr, rate_limiter)
        if not allowed:
            st.error(err)
            return

        llm_service, _ = build_active_llm_service(
            session_mgr, config, max_tokens=4096
        )
        if llm_service is None:
            st.warning(
                "Для анализа настройте API-ключ или включите бесплатный Демо-режим."
            )
            return

        with st.spinner("AI анализирует требования, оценивает сроки и риски..."):
            pm_service = JiraPMService(llm_service)
            try:
                result = pm_service.analyze(
                    requirements=requirements,
                    analysis_types=selected_types,
                )
                session_mgr.state["jira_result"] = result
            except ProviderRateLimitError as exc:
                if session_mgr.state.get("auth_mode") == "demo":
                    rate_limiter.mark_upstream_exhausted()
                st.error(f"⚠️ {exc}")
            except ProviderClientError as exc:
                st.error(f"❌ {exc}")

    result = session_mgr.state.get("jira_result")
    if result is None:
        return

    st.divider()
    st.subheader("📊 Результаты анализа")
    if result.telemetry:
        st.caption(result.telemetry.format_line())

    # --- Таблица задач ---
    if result.issues:
        table_data = [
            {
                "Issue Type": issue.issue_type,
                "Summary": issue.summary,
                "Description": issue.description,
                "Acceptance Criteria": issue.acceptance_criteria,
                "Priority": issue.priority,
                "Original Estimate (h)": issue.original_estimate_hours,
                "Story Points": issue.story_points,
                "Parent": issue.parent_summary or "",
            }
            for issue in result.issues
        ]
        st.dataframe(table_data, use_container_width=True, hide_index=True)

        # --- Экспорт ---
        csv_content = JiraPMService.export_jira_csv(result.issues)
        md_content = result.report_markdown
        col_csv, col_md = st.columns(2)
        with col_csv:
            st.download_button(
                label="📥 Скачать Jira CSV",
                data=csv_content,
                file_name="jira_import.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with col_md:
            st.download_button(
                label="📥 Скачать отчёт (.md)",
                data=md_content,
                file_name="pm_report.md",
                mime="text/markdown",
                use_container_width=True,
            )

        # --- Отправка в Jira (опционально) ---
        if st.button("🚀 Отправить задачи в Jira", use_container_width=True):
            open_jira_push_dialog(result.issues)
    else:
        st.info("Модель не вернула структурированных задач. Попробуйте уточнить требования.")

    # --- Риски и вопросы ---
    if result.risks:
        with st.expander(f"🚨 Риски ({len(result.risks)})"):
            risk_data = [
                {
                    "Риск": risk.risk,
                    "Вероятность": risk.probability,
                    "Влияние": risk.impact,
                    "Митигация": risk.mitigation,
                }
                for risk in result.risks
            ]
            st.dataframe(risk_data, use_container_width=True, hide_index=True)

    if result.clarifying_questions:
        with st.expander(f"❓ Уточняющие вопросы ({len(result.clarifying_questions)})"):
            for question in result.clarifying_questions:
                st.markdown(f"- {question}")

    # --- Сырой ответ модели (для отладки) ---
    with st.expander("🧪 Сырой ответ модели"):
        st.markdown(result.raw_response)


# =====================================================================
# 9. Главная функция приложения
# =====================================================================


def main() -> None:
    """Точка входа в приложение."""
    inject_custom_css()

    config = get_app_config()
    rate_limiter = get_global_rate_limiter(
        daily_limit=config.demo_daily_global_limit,
        session_limit=config.demo_session_limit,
    )
    session_mgr = ChatSessionManager(
        state=st.session_state,
        default_demo_enabled=config.is_demo_configured,
        default_temperature=config.default_temperature,
    )

    render_sidebar(session_mgr, config, rate_limiter)

    workspace_mode = session_mgr.state.get("workspace_mode", "chat")
    if workspace_mode == "jira":
        render_jira_workspace(session_mgr, config, rate_limiter)
    else:
        render_chat_workspace(session_mgr, config, rate_limiter)


if __name__ == "__main__":
    main()

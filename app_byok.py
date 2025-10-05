"""
AI Tutor - Streamlit приложение с поддержкой BYOK (Bring Your Own API Key)

Это приложение позволяет пользователям использовать собственный OpenAI API ключ
для взаимодействия с различными моделями GPT.

Основные возможности:
- Ввод собственного API ключа (хранится только в session_state)
- Выбор модели (gpt-4o, gpt-4-turbo, gpt-4o-mini, gpt-3.5-turbo)
- Настройка температуры (0.0 - 1.0)
- Минималистичный тёмный интерфейс
- Управление чатами (создание, переключение, удаление)
"""

import time
import uuid
from datetime import datetime
from typing import List, Dict, Optional

import streamlit as st
from openai import OpenAI

# ============================================
# Настройка страницы и темы
# ============================================

st.set_page_config(
    page_title="AI Tutor - BYOK",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Применяем тёмную тему через CSS
st.markdown(
    """
    <style>
    /* Тёмная тема для всего приложения */
    .stApp {
        background-color: #1E1E1E;
        color: #E0E0E0;
    }
    
    /* Стилизация expander */
    .streamlit-expanderHeader {
        background-color: #2D2D2D;
        border-radius: 5px;
    }
    
    /* Стилизация кнопок */
    .stButton>button {
        background-color: #2D2D2D;
        color: #E0E0E0;
        border: 1px solid #404040;
        border-radius: 5px;
    }
    
    .stButton>button:hover {
        background-color: #3D3D3D;
        border-color: #505050;
    }
    
    /* Стилизация текстовых полей */
    .stTextInput>div>div>input,
    .stTextArea>div>div>textarea {
        background-color: #2D2D2D;
        color: #E0E0E0;
        border: 1px solid #404040;
        border-radius: 5px;
    }
    
    /* Стилизация сообщений чата */
    .stChatMessage {
        background-color: #2D2D2D;
        border-radius: 10px;
        padding: 10px;
        margin: 5px 0;
    }
    
    /* Предупреждения и уведомления */
    .stAlert {
        background-color: #2D2D2D;
        border-radius: 5px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================
# Инициализация состояния сессии
# ============================================


def init_session_state():
    """
    Инициализирует все необходимые переменные состояния сессии.

    Переменные состояния:
    - api_key: OpenAI API ключ (хранится только в памяти)
    - model: Выбранная модель
    - temperature: Температура для генерации
    - chats: Словарь всех чатов {chat_id: chat_data}
    - current_chat_id: ID активного чата
    - chat_counter: Счётчик для автоматических названий чатов
    """
    if "api_key" not in st.session_state:
        st.session_state.api_key = ""

    if "model" not in st.session_state:
        st.session_state.model = "gpt-4o-mini"

    if "temperature" not in st.session_state:
        st.session_state.temperature = 0.7

    if "chats" not in st.session_state:
        # Создаём первый чат по умолчанию
        default_chat_id = f"chat_{uuid.uuid4().hex[:8]}"
        st.session_state.chats = {
            default_chat_id: {
                "title": "Новый чат 1",
                "history": [],
                "created_at": datetime.now(),
            }
        }
        st.session_state.current_chat_id = default_chat_id
        st.session_state.chat_counter = 2


# ============================================
# Функции для работы с чатами
# ============================================


def create_new_chat() -> str:
    """
    Создаёт новый чат и возвращает его ID.

    Returns:
        str: ID созданного чата
    """
    chat_id = f"chat_{uuid.uuid4().hex[:8]}"
    chat_title = f"Новый чат {st.session_state.chat_counter}"
    st.session_state.chat_counter += 1

    st.session_state.chats[chat_id] = {
        "title": chat_title,
        "history": [],
        "created_at": datetime.now(),
    }

    return chat_id


def switch_chat(chat_id: str):
    """
    Переключает активный чат.

    Args:
        chat_id: ID чата для переключения
    """
    if chat_id in st.session_state.chats:
        st.session_state.current_chat_id = chat_id


def delete_chat(chat_id: str):
    """
    Удаляет чат по ID.

    Args:
        chat_id: ID чата для удаления
    """
    if chat_id in st.session_state.chats:
        del st.session_state.chats[chat_id]

        # Если удалили активный чат, переключаемся на другой
        if st.session_state.current_chat_id == chat_id:
            remaining_chats = list(st.session_state.chats.keys())
            if remaining_chats:
                st.session_state.current_chat_id = remaining_chats[0]
            else:
                # Если чатов не осталось, создаём новый
                new_chat_id = create_new_chat()
                st.session_state.current_chat_id = new_chat_id


def get_current_chat() -> Dict:
    """
    Возвращает данные текущего активного чата.

    Returns:
        Dict: Данные чата (title, history, created_at)
    """
    chat_id = st.session_state.current_chat_id
    return st.session_state.chats[chat_id]


def add_message(role: str, content: str):
    """
    Добавляет сообщение в историю текущего чата.

    Args:
        role: Роль отправителя ('user' или 'assistant')
        content: Содержимое сообщения
    """
    current_chat = get_current_chat()
    current_chat["history"].append(
        {"role": role, "content": content, "timestamp": datetime.now()}
    )


# ============================================
# Функция для вызова OpenAI API
# ============================================


def call_openai_api(messages: List[Dict], api_key: str) -> Optional[str]:
    """
    Вызывает OpenAI API для получения ответа от модели.

    Args:
        messages: Список сообщений в формате OpenAI
        api_key: OpenAI API ключ

    Returns:
        Optional[str]: Ответ модели или None в случае ошибки
    """
    try:
        client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model=st.session_state.model,
            messages=messages,
            temperature=st.session_state.temperature,
        )

        return response.choices[0].message.content

    except Exception as e:
        st.error(f"❌ Ошибка при вызове API: {str(e)}")
        return None


# ============================================
# Вспомогательные функции для UI
# ============================================


def format_timestamp(dt: datetime) -> str:
    """
    Форматирует временную метку в читаемый вид.

    Args:
        dt: Объект datetime

    Returns:
        str: Отформатированное время в формате HH:MM:SS
    """
    return dt.strftime("%H:%M:%S")


def display_message(role: str, content: str, timestamp: datetime):
    """
    Отображает сообщение в чате с временной меткой.

    Args:
        role: Роль отправителя ('user' или 'assistant')
        content: Содержимое сообщения
        timestamp: Время отправки сообщения
    """
    with st.chat_message(role):
        st.write(content)
        time_str = format_timestamp(timestamp)
        st.markdown(
            f"<div style='font-size:0.75em; color:#888; "
            f"text-align:right; margin-top:-10px;'>{time_str}</div>",
            unsafe_allow_html=True,
        )


def show_typing_indicator(placeholder, duration: float = 1.5):
    """
    Отображает анимированный индикатор печати "🤖 Печатает...".

    Args:
        placeholder: st.empty() объект для обновления
        duration: Длительность анимации в секундах
    """
    dots_states = [".", "..", "..."]
    iterations = int(duration / 0.3)

    for i in range(iterations):
        dots = dots_states[i % len(dots_states)]
        placeholder.markdown(
            f"<div style='color: #888; font-style: italic;'>"
            f"🤖 Печатает{dots}</div>",
            unsafe_allow_html=True,
        )
        time.sleep(0.3)


# ============================================
# Главная функция приложения
# ============================================


def main():
    """Главная функция - точка входа в приложение."""
    # Инициализируем состояние сессии
    init_session_state()

    # ============================================
    # САЙДБАР - Настройки и управление
    # ============================================

    with st.sidebar:
        st.title("⚙️ Настройки")

        # ============================================
        # Секция 1: Настройки API
        # ============================================

        with st.expander("🔑 Настройки API", expanded=True):
            st.markdown("### Ввод API ключа")
            st.caption(
                "Введите свой OpenAI API ключ. " "Ключ хранится только в памяти сессии."
            )

            # Поле ввода API ключа (скрытое, как пароль)
            api_key_input = st.text_input(
                "OpenAI API Key",
                type="password",
                value=st.session_state.api_key,
                placeholder="sk-...",
                help="Ваш API ключ OpenAI. Начинается с 'sk-'",
                key="api_key_input",
            )

            # Кнопка сохранения ключа
            if st.button("💾 Сохранить ключ", use_container_width=True):
                if api_key_input.strip():
                    st.session_state.api_key = api_key_input.strip()
                    st.success("✅ Ключ сохранён. Можно работать.")
                else:
                    st.warning("⚠️ Введите корректный API ключ")

            # Кнопка очистки ключа
            if st.session_state.api_key:
                if st.button("🗑️ Очистить ключ", use_container_width=True):
                    st.session_state.api_key = ""
                    st.info("🔄 Ключ удалён из сессии")
                    st.rerun()

            st.divider()

            # Выбор модели
            st.markdown("### Выбор модели")
            available_models = [
                "gpt-4o",
                "gpt-4-turbo",
                "gpt-4o-mini",
                "gpt-3.5-turbo",
            ]

            selected_model = st.selectbox(
                "Модель",
                available_models,
                index=available_models.index(st.session_state.model),
                help="Выберите модель GPT для генерации ответов",
            )

            if selected_model != st.session_state.model:
                st.session_state.model = selected_model

            st.divider()

            # Настройка температуры
            st.markdown("### Температура")
            st.caption("Контролирует креативность ответов модели")

            temperature = st.slider(
                "Температура",
                min_value=0.0,
                max_value=1.0,
                value=st.session_state.temperature,
                step=0.1,
                help="0.0 = детерминированные ответы, 1.0 = максимальная креативность",
            )

            if temperature != st.session_state.temperature:
                st.session_state.temperature = temperature

            # Отображение текущих настроек
            st.caption(
                f"**Текущие настройки:** {st.session_state.model}, "
                f"температура {st.session_state.temperature}"
            )

        st.divider()

        # ============================================
        # Секция 2: Управление чатами
        # ============================================

        st.subheader("💬 Управление чатами")

        # Кнопка создания нового чата
        if st.button("🆕 Новый чат", use_container_width=True):
            new_chat_id = create_new_chat()
            switch_chat(new_chat_id)
            st.rerun()

        st.divider()

        # Список всех чатов
        st.caption("**Ваши чаты:**")

        # Инициализируем состояние для подтверждения удаления
        if "delete_confirm" not in st.session_state:
            st.session_state.delete_confirm = None

        # Обработка подтверждённого удаления
        if st.session_state.delete_confirm:
            delete_id = st.session_state.delete_confirm
            delete_chat(delete_id)
            st.session_state.delete_confirm = None
            st.success("✅ Чат удалён")
            st.rerun()

        # Отображаем список чатов
        for chat_id, chat_data in st.session_state.chats.items():
            title = chat_data["title"]
            message_count = len(chat_data["history"])
            is_current = chat_id == st.session_state.current_chat_id

            # Формируем метку
            label = f"💬 {title} ({message_count})"
            button_type = "primary" if is_current else "secondary"

            # Две колонки: название чата и кнопка удаления
            col1, col2 = st.columns([0.85, 0.15], gap="small")

            with col1:
                if st.button(
                    label,
                    key=f"chat_btn_{chat_id}",
                    use_container_width=True,
                    type=button_type,
                ):
                    switch_chat(chat_id)
                    st.rerun()

            with col2:
                if st.button(
                    "🗑",
                    key=f"delete_btn_{chat_id}",
                    help="Удалить чат",
                    use_container_width=True,
                ):
                    st.session_state.pending_delete = chat_id
                    st.rerun()

        # Модальное окно подтверждения удаления
        if st.session_state.get("pending_delete"):
            pending_id = st.session_state.pending_delete
            pending_chat = st.session_state.chats.get(pending_id)

            if pending_chat:
                st.warning(
                    f"⚠️ Удалить чат '{pending_chat['title']}'? "
                    f"Это действие нельзя отменить."
                )

                col1, col2 = st.columns(2)

                with col1:
                    if st.button(
                        "✅ Да",
                        key="confirm_delete",
                        type="primary",
                        use_container_width=True,
                    ):
                        st.session_state.delete_confirm = pending_id
                        st.session_state.pop("pending_delete", None)
                        st.rerun()

                with col2:
                    if st.button(
                        "❌ Нет",
                        key="cancel_delete",
                        use_container_width=True,
                    ):
                        st.session_state.pop("pending_delete", None)
                        st.rerun()

    # ============================================
    # ОСНОВНАЯ ОБЛАСТЬ - Чат
    # ============================================

    st.title("🤖 AI Tutor - BYOK")
    st.caption("Используйте свой OpenAI API ключ для работы с моделями GPT")

    # Проверяем наличие API ключа
    if not st.session_state.api_key:
        # Если ключ не введён, показываем предупреждение
        st.warning(
            "⚠️ **API ключ не введён**\n\n"
            "Пожалуйста, введите свой OpenAI API ключ "
            "в разделе '🔑 Настройки API' на боковой панели, "
            "чтобы начать работу с моделью."
        )

        # Показываем инструкцию
        with st.expander("📖 Как получить API ключ?"):
            st.markdown(
                """
                1. Перейдите на [platform.openai.com](https://platform.openai.com/)
                2. Войдите в свой аккаунт или создайте новый
                3. Перейдите в раздел **API Keys**
                4. Нажмите **Create new secret key**
                5. Скопируйте ключ и вставьте его в поле выше
                
                ⚠️ **Важно:** Храните ключ в безопасности! 
                Не делитесь им с другими.
                """
            )

        # Блокируем дальнейшую работу
        st.stop()

    # ============================================
    # Отображение истории текущего чата
    # ============================================

    current_chat = get_current_chat()
    chat_history = current_chat["history"]

    # Показываем все сообщения из истории
    for msg in chat_history:
        display_message(msg["role"], msg["content"], msg["timestamp"])

    # ============================================
    # Поле ввода нового сообщения
    # ============================================

    prompt = st.chat_input("Введите ваше сообщение...")

    if prompt:
        # Добавляем сообщение пользователя
        add_message("user", prompt)

        # Отображаем сообщение пользователя
        display_message("user", prompt, datetime.now())

        # Подготавливаем историю для API
        messages = [
            {"role": msg["role"], "content": msg["content"]} for msg in chat_history
        ]

        # Создаём placeholder для индикатора печати
        typing_placeholder = st.empty()

        # Получаем ответ от модели
        with st.chat_message("assistant"):
            # Показываем индикатор "Печатает..."
            with typing_placeholder.container():
                show_typing_indicator(typing_placeholder, duration=1.5)

            # Вызываем API
            response = call_openai_api(messages, st.session_state.api_key)

            # Очищаем индикатор
            typing_placeholder.empty()

            if response:
                # Добавляем ответ в историю
                add_message("assistant", response)

                # Отображаем ответ
                st.write(response)
                time_str = format_timestamp(datetime.now())
                st.markdown(
                    f"<div style='font-size:0.75em; color:#888; "
                    f"text-align:right; margin-top:-10px;'>{time_str}</div>",
                    unsafe_allow_html=True,
                )

                # Перезагружаем страницу для обновления истории
                st.rerun()


if __name__ == "__main__":
    main()

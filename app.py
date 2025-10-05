import time
import uuid
from datetime import datetime

import streamlit as st
import tiktoken

from src.chat_manager import ChatManager

# ============================================
# Вспомогательные функции для UX-улучшений
# ============================================


def count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    """
    Подсчитывает количество токенов в тексте для заданной модели.

    Args:
        text: Текст для подсчёта токенов
        model: Название модели для выбора подходящего токенизатора

    Returns:
        Количество токенов в тексте
    """
    try:
        enc = tiktoken.encoding_for_model(model)
        return len(enc.encode(text))
    except Exception:
        # Если модель не поддерживается, используем cl100k_base (GPT-4/3.5)
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))


def calculate_total_tokens(chat_history: list, model: str = "gpt-3.5-turbo") -> int:
    """
    Вычисляет общее количество токенов во всей истории чата.

    Args:
        chat_history: Список сообщений чата
        model: Название модели для токенизации

    Returns:
        Суммарное количество токенов
    """
    total = 0
    for message in chat_history:
        content = message.get("content", "")
        total += count_tokens(content, model)
    return total


def show_typing_indicator(placeholder, duration: float = 2.0):
    """
    Отображает анимированный индикатор "🤖 Печатает..." с пульсирующими точками.

    Args:
        placeholder: st.empty() объект для обновления содержимого
        duration: Общая длительность анимации в секундах
    """
    dots_states = [".", "..", "..."]
    iterations = int(duration / 0.3)  # Каждая итерация длится 0.3 секунды

    for i in range(iterations):
        dots = dots_states[i % len(dots_states)]
        placeholder.markdown(
            f"<div style='color: #888; font-style: italic;'>🤖 Печатает{dots}</div>",
            unsafe_allow_html=True,
        )
        time.sleep(0.3)


def format_timestamp(dt: datetime = None) -> str:
    """
    Форматирует временную метку в читаемый вид.

    Args:
        dt: Объект datetime (если None, используется текущее время)

    Returns:
        Строка с отформатированным временем в формате HH:MM:SS
    """
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%H:%M:%S")


def display_message_with_timestamp(role: str, content: str):
    """
    Отображает сообщение чата с временной меткой внизу.

    Args:
        role: Роль отправителя ('user' или 'assistant')
        content: Содержимое сообщения
    """
    with st.chat_message(role):
        st.write(content)
        # Отображаем время сообщения серым текстом справа
        timestamp = format_timestamp()
        st.markdown(
            f"<div style='font-size:0.8em; color:#888; text-align:right; "
            f"margin-top:-10px;'>{timestamp}</div>",
            unsafe_allow_html=True,
        )


# ============================================
# Настройка страницы
# ============================================

st.set_page_config(
    page_title="AI Tutor Chat",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================
# Инициализация состояния сессии для BYOK
# ============================================


def init_session_state():
    """
    Инициализирует переменные состояния для BYOK и чатов.

    Переменные:
    - api_key: OpenAI API ключ (вводится пользователем)
    - chats: словарь всех чатов {chat_id: {"title": str, "messages": list}}
    - active_chat: ID текущего активного чата
    - chat_counter: счётчик для нумерации новых чатов
    """
    # Инициализация API ключа
    if "api_key" not in st.session_state:
        st.session_state.api_key = ""

    # Инициализация чатов - словарь всех чатов
    if "chats" not in st.session_state:
        # Создаём первый чат по умолчанию
        first_chat_id = f"chat_{uuid.uuid4().hex[:8]}"
        st.session_state.chats = {
            first_chat_id: {
                "title": "Новый чат 1",
                "messages": [],  # История сообщений [{role: str, content: str}]
            }
        }
        st.session_state.active_chat = first_chat_id  # Устанавливаем как активный
        st.session_state.chat_counter = 2  # Счётчик для следующих чатов

    # Инициализация активного чата (если не задан)
    if "active_chat" not in st.session_state:
        # Если по какой-то причине active_chat не задан, берём первый чат
        if st.session_state.chats:
            st.session_state.active_chat = list(st.session_state.chats.keys())[0]
        else:
            st.session_state.active_chat = None

    # Инициализация счётчика (если не задан)
    if "chat_counter" not in st.session_state:
        st.session_state.chat_counter = len(st.session_state.chats) + 1


# Инициализация менеджера чатов
def get_chat_manager():
    """
    Создаёт экземпляр ChatManager с API ключом из session_state.

    Returns:
        ChatManager или None, если ключ не введён
    """
    if st.session_state.api_key:
        try:
            return ChatManager(api_key=st.session_state.api_key)
        except Exception as e:
            st.error(f"❌ Ошибка инициализации ChatManager: {str(e)}")
            return None
    return None


def main():
    """Главная функция приложения с поддержкой BYOK."""
    # Инициализируем состояние сессии
    init_session_state()

    # ============================================
    # Проверка API ключа
    # ============================================

    # Если API ключ не введён, показываем форму для ввода
    if not st.session_state.api_key:
        st.title("🤖 AI Tutor Chat")
        st.caption("Для начала работы введите свой OpenAI API ключ")

        # Центрируем форму
        col1, col2, col3 = st.columns([1, 2, 1])

        with col2:
            st.markdown("### 🔑 Ввод API ключа")
            st.info(
                "Ваш API ключ будет использоваться только в текущей сессии "
                "и не будет сохранён на диск."
            )

            # Поле ввода API ключа
            api_key_input = st.text_input(
                "OpenAI API Key",
                type="password",
                placeholder="sk-...",
                help="Введите ваш OpenAI API ключ",
                key="api_key_input_field",
            )

            # Кнопка для сохранения ключа
            if st.button("💾 Сохранить и начать работу", use_container_width=True):
                if api_key_input.strip():
                    st.session_state.api_key = api_key_input.strip()
                    st.success("✅ Ключ сохранён. Инициализация...")
                    st.rerun()
                else:
                    st.error("❌ Пожалуйста, введите корректный API ключ")

            st.divider()

            # Инструкция по получению ключа
            with st.expander("📖 Как получить API ключ?"):
                st.markdown(
                    """
                    1. Перейдите на [platform.openai.com](https://platform.openai.com/)
                    2. Войдите в свой аккаунт или создайте новый
                    3. Перейдите в раздел **API Keys**
                    4. Нажмите **Create new secret key**
                    5. Скопируйте ключ и вставьте его выше
                    
                    ⚠️ **Важно:** Храните ключ в безопасности!
                    """
                )

        # Останавливаем выполнение, пока не введён ключ
        st.stop()

    # ============================================
    # Инициализация ChatManager с API ключом
    # ============================================

    chat_manager = get_chat_manager()

    if chat_manager is None:
        st.error("❌ Ошибка инициализации ChatManager. Проверьте API ключ.")
        if st.button("🔄 Сбросить ключ и попробовать снова"):
            st.session_state.api_key = ""
            st.rerun()
        st.stop()

    # ============================================
    # САЙДБАР (боковая панель с настройками)
    # ============================================

    # Добавляем CSS для центрирования иконки удаления
    st.markdown(
        """
    <style>
    /* Центрирование иконки удаления по вертикали */
    /* Находим все кнопки удаления и центрируем их */
    [data-testid="column"] > div > div > div > button[kind="secondary"] {
        margin-top: auto;
        margin-bottom: auto;
    }
    
    /* Альтернативный способ: центрирование через flex для второй колонки */
    div[data-testid="stHorizontalBlock"] > div:nth-child(2) {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }
    
    /* Убираем лишние отступы у кнопки удаления */
    div[data-testid="stHorizontalBlock"] > div:nth-child(2) button {
        margin: 0 !important;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.title("💬 Настройки чата")

        # Показываем статус API ключа
        st.success("✅ API ключ активен")

        # Кнопка для очистки ключа
        if st.button("🗑️ Очистить ключ", use_container_width=True):
            st.session_state.api_key = ""
            st.session_state.chat_manager_initialized = False
            st.info("🔄 Ключ удалён. Перезагрузка...")
            st.rerun()

        st.divider()

        # --- Кнопка создания нового чата ---
        if st.button("🆕 Новый чат", use_container_width=True):
            # Генерируем уникальный ID для нового чата
            new_chat_id = f"chat_{uuid.uuid4().hex[:8]}"
            # Создаём новый чат в session_state
            st.session_state.chats[new_chat_id] = {
                "title": f"Новый чат {st.session_state.chat_counter}",
                "messages": [],
            }
            st.session_state.chat_counter += 1
            # Делаем новый чат активным
            st.session_state.active_chat = new_chat_id
            st.rerun()

        st.divider()

        # --- История чатов ---
        st.subheader("История чатов")

        if not st.session_state.chats:
            st.info("Пока нет активных чатов")

        # Инициализируем состояние для подтверждения удаления
        if "delete_confirm" not in st.session_state:
            st.session_state["delete_confirm"] = None

        # --- Обработка подтверждённого удаления чата ---
        if st.session_state.get("delete_confirm"):
            delete_id = st.session_state["delete_confirm"]
            # Удаляем чат из session_state
            if delete_id in st.session_state.chats:
                del st.session_state.chats[delete_id]

                # Проверяем, остались ли ещё чаты
                if not st.session_state.chats:
                    # Если все чаты удалены, создаём новый
                    new_chat_id = f"chat_{uuid.uuid4().hex[:8]}"
                    st.session_state.chats[new_chat_id] = {
                        "title": f"Новый чат {st.session_state.chat_counter}",
                        "messages": [],
                    }
                    st.session_state.chat_counter += 1
                    st.session_state.active_chat = new_chat_id
                    st.session_state["delete_feedback"] = (
                        "✅ Чат удалён. Создан новый чат."
                    )
                else:
                    # Если удалили активный чат, переключаемся на первый
                    if st.session_state.active_chat == delete_id:
                        st.session_state.active_chat = list(
                            st.session_state.chats.keys()
                        )[0]
                    st.session_state["delete_feedback"] = "✅ Чат удалён успешно"
            else:
                st.session_state["delete_feedback"] = "❌ Ошибка при удалении чата"
            # Сбрасываем состояние подтверждения
            st.session_state["delete_confirm"] = None
            st.rerun()

        # Показываем уведомление об удалении
        delete_feedback = st.session_state.pop("delete_feedback", None)
        if delete_feedback:
            st.success(delete_feedback)

        # Отображаем список чатов с кнопками удаления
        for chat_id, chat_data in st.session_state.chats.items():
            title = chat_data["title"]
            message_count = len(chat_data["messages"]) // 2  # Пары: user+bot

            # Формируем метку с количеством сообщений для отображения
            if message_count:
                label = f"💬 {title} ({message_count})"
            else:
                label = f"💬 {title}"

            # Определяем тип кнопки (выделяем активный чат)
            is_current = chat_id == st.session_state.active_chat
            button_type = "primary" if is_current else "secondary"

            # === СТАБИЛИЗАЦИЯ ВЫРАВНИВАНИЯ ИКОНКИ УДАЛЕНИЯ ===
            #
            # Проблема: при изменении ширины sidebar иконка 🗑️ может
            # "съезжать" относительно названия чата, создавая визуальный
            # дискомфорт.
            #
            # Решение: используем st.columns с фиксированным процентным
            # соотношением [0.85, 0.15], что означает:
            # - col1 занимает 85% доступной ширины (название чата)
            # - col2 занимает 15% доступной ширины (кнопка удаления)
            #
            # Почему это работает:
            # 1. Процентное соотношение остаётся постоянным независимо
            #    от абсолютной ширины sidebar
            # 2. При ресайзе sidebar обе колонки масштабируются
            #    пропорционально, сохраняя относительное положение
            # 3. gap="small" создаёт минимальный отступ между колонками,
            #    который также масштабируется пропорционально
            # 4. use_container_width=True в обеих кнопках гарантирует,
            #    что они заполняют всю доступную ширину своей колонки
            #
            # Результат: иконка 🗑️ всегда остаётся на одном
            # горизонтальном уровне с названием чата, независимо от
            # ширины sidebar (100px или 500px — не важно).
            #
            col1, col2 = st.columns([0.85, 0.15], gap="small")

            with col1:
                # Кнопка переключения на выбранный чат
                # use_container_width=True — кнопка растягивается на всю
                # ширину колонки (85% от доступного пространства)
                # Это обеспечивает адаптивность при изменении размера
                if st.button(
                    label,
                    key=f"chat_btn_{chat_id}",
                    use_container_width=True,
                    type=button_type,
                ):
                    # Переключаемся на выбранный чат
                    st.session_state.active_chat = chat_id
                    st.rerun()

            with col2:
                # Кнопка удаления чата с автоматическим центрированием
                # Занимает фиксированные 15% от общей ширины
                # CSS выше автоматически центрирует кнопку по вертикали
                # Благодаря процентному соотношению колонок, иконка
                # всегда остаётся справа на одном уровне с названием

                # Кнопка удаления с иконкой корзины
                # Центрируется автоматически через CSS (см. начало main())
                if st.button(
                    "🗑",
                    key=f"delete_btn_{chat_id}",
                    help="Удалить чат",
                    use_container_width=True,
                ):
                    # Сохраняем ID чата для подтверждения удаления
                    st.session_state["pending_delete"] = chat_id
                    st.rerun()

        # --- Модальное окно подтверждения удаления ---
        # Отображается, когда пользователь нажимает на 🗑️
        if st.session_state.get("pending_delete"):
            pending_id = st.session_state["pending_delete"]

            # Находим название чата для отображения в предупреждении
            pending_title = st.session_state.chats.get(pending_id, {}).get(
                "title", pending_id
            )

            # Предупреждение о необратимости действия
            st.warning(
                f"⚠️ Вы уверены, что хотите удалить чат "
                f'"{pending_title}"? Это действие нельзя отменить.'
            )

            # Две колонки для кнопок подтверждения и отмены
            # Соотношение 1:1 (50% на 50%) для симметрии
            confirm_col1, confirm_col2 = st.columns(2)

            with confirm_col1:
                # Кнопка подтверждения удаления (красная, primary)
                if st.button(
                    "✅ Да, удалить",
                    key="confirm_delete",
                    type="primary",
                    use_container_width=True,
                ):
                    # Подтверждаем удаление — перемещаем из pending в confirm
                    st.session_state["delete_confirm"] = pending_id
                    st.session_state.pop("pending_delete", None)
                    st.rerun()

            with confirm_col2:
                # Кнопка отмены (серая, secondary)
                if st.button(
                    "❌ Отмена",
                    key="cancel_delete",
                    use_container_width=True,
                ):
                    # Отменяем удаление
                    st.session_state.pop("pending_delete", None)
                    st.rerun()

        # Переименование чата
        st.subheader("Переименовать чат")

        # Получаем текущее название активного чата
        active_chat = st.session_state.active_chat
        current_title = st.session_state.chats[active_chat]["title"]

        new_title = st.text_input(
            "Название текущего чата",
            value=current_title,
            max_chars=60,
            help=("Введите название, чтобы легче отличать беседы."),
            key="chat_title_input",
        )

        if st.button(
            "💾 Сохранить название",
            use_container_width=True,
            help="Фиксирует выбранное название за текущим чатом.",
        ):
            if new_title.strip():
                st.session_state.chats[active_chat]["title"] = new_title
                st.session_state["rename_feedback"] = "✅ Название чата обновлено"
                st.rerun()

        rename_feedback = st.session_state.pop("rename_feedback", None)
        if rename_feedback:
            st.caption(rename_feedback)

        st.divider()

        # Экспорт чата
        st.subheader("Экспорт")

        # Получаем историю текущего активного чата
        chat_history = st.session_state.chats[active_chat]["messages"]

        # Проверяем, есть ли сообщения для экспорта
        if chat_history:
            # Формируем текстовое содержимое файла
            export_lines = []
            for message in chat_history:
                role = message.get("role", "")
                content = message.get("content", "")

                # Преобразуем роль в читаемый формат
                if role == "user":
                    export_lines.append(f"User: {content}")
                elif role == "assistant":
                    export_lines.append(f"AI: {content}")

                # Добавляем пустую строку между сообщениями
                export_lines.append("")

            # Объединяем все строки в один текст
            export_text = "\n".join(export_lines)

            # Формируем имя файла с названием чата и датой
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            chat_title = st.session_state.chats[active_chat]["title"]
            # Убираем недопустимые символы из имени файла
            safe_title = "".join(
                c for c in chat_title if c.isalnum() or c in (" ", "-", "_")
            ).strip()
            filename = f"{safe_title}_{timestamp}.txt"

            # Кнопка скачивания
            st.download_button(
                label="📥 Скачать чат",
                data=export_text,
                file_name=filename,
                mime="text/plain",
                use_container_width=True,
                help="Сохранить историю текущего чата в текстовый файл",
            )
        else:
            # Если чат пустой, показываем информационное сообщение
            st.info("Нет сообщений для экспорта")

        st.divider()

        # --- Быстрые промпты (шаблоны сообщений) ---
        st.subheader("Быстрые промпты")

        # Инициализируем состояние для поля ввода
        if "prompt_input" not in st.session_state:
            st.session_state["prompt_input"] = ""

        # Словарь с готовыми шаблонами промптов
        # Ключ — идентификатор, значение — текст шаблона
        prompt_templates = {
            "essay": "Напиши подробное эссе на тему: ",
            "explain": "Объясни следующий код:\n```\n[вставь код здесь]\n```",
            "summarize": "Кратко резюмируй следующий текст:\n",
        }

        # === СТАБИЛИЗАЦИЯ ИКОНОК БЫСТРЫХ ПРОМПТОВ ===
        #
        # Используем три колонки с равным соотношением [1, 1, 1]
        # Это означает, что каждая кнопка занимает ровно 33.3%
        # от доступной ширины sidebar.
        #
        # При изменении ширины sidebar все три кнопки масштабируются
        # пропорционально, сохраняя выравнивание и интервалы.
        #
        col1, col2, col3 = st.columns(3)

        with col1:
            # Кнопка "Написать эссе" (✍️)
            if st.button(
                "✍️",
                key="prompt_essay",
                help="Написать эссе",
                use_container_width=True,
            ):
                # Вставляем шаблон эссе в поле ввода
                st.session_state["prompt_input"] = prompt_templates["essay"]
                st.rerun()

        with col2:
            # Кнопка "Объяснить код" (🔍)
            if st.button(
                "🔍",
                key="prompt_explain",
                help="Объяснить код",
                use_container_width=True,
            ):
                # Вставляем шаблон объяснения кода в поле ввода
                st.session_state["prompt_input"] = prompt_templates["explain"]
                st.rerun()

        with col3:
            # Кнопка "Резюмировать" (📝)
            if st.button(
                "📝",
                key="prompt_summarize",
                help="Резюмировать текст",
                use_container_width=True,
            ):
                # Вставляем шаблон в поле ввода
                st.session_state["prompt_input"] = prompt_templates["summarize"]
                st.rerun()

        st.divider()

        # Правила общения
        st.subheader("Правила общения")

        # Инициализируем состояние для правил общения
        if "chat_rules" not in st.session_state:
            st.session_state["chat_rules"] = ""

        # Текстовое поле для ввода правил
        # Значение сохраняется автоматически в st.session_state["chat_rules"]
        chat_rules = st.text_area(
            "Инструкции для AI",
            value=st.session_state["chat_rules"],
            height=100,
            placeholder=(
                "Например:\n"
                "- Отвечай кратко и по существу\n"
                "- Объясняй как опытный преподаватель\n"
                "- Используй примеры из реальной жизни"
            ),
            help=(
                "Эти инструкции будут добавлены как системный промпт "
                "перед каждым ответом модели"
            ),
            key="chat_rules",
        )

        # Показываем статус правил
        if chat_rules.strip():
            st.caption("✅ Правила активны")
        else:
            st.caption("ℹ️ Правила не заданы")

        st.divider()

        # Настройки
        st.subheader("Настройки")
        current_settings = chat_manager.get_current_settings()
        st.session_state.setdefault(
            "temperature_setting", float(current_settings["temperature"])
        )
        st.session_state.setdefault(
            "model_setting",
            current_settings["model_name"],
        )

        reset_clicked = st.button(
            "↩️ Сбросить настройки",
            use_container_width=True,
            help="Вернуть параметры модели к значениям по умолчанию.",
        )

        if reset_clicked:
            chat_manager.reset_settings()
            current_settings = chat_manager.get_current_settings()
            st.session_state["temperature_setting"] = float(
                current_settings["temperature"]
            )
            st.session_state["model_setting"] = current_settings["model_name"]

        model_options = current_settings["available_models"]
        if st.session_state["model_setting"] not in model_options:
            st.session_state["model_setting"] = current_settings["model_name"]

        temperature = st.slider(
            "Температура",
            min_value=0.0,
            max_value=1.0,
            value=float(st.session_state["temperature_setting"]),
            step=0.05,
            help="Чем выше температура, тем разнообразнее ответы модели.",
            key="temperature_setting",
        )

        model_name = st.selectbox(
            "Модель",
            model_options,
            index=model_options.index(st.session_state["model_setting"]),
            help="Выберите модель, которую хотите использовать для ответов.",
            key="model_setting",
        )

        if (
            abs(temperature - current_settings["temperature"]) > 1e-9
            or model_name != current_settings["model_name"]
        ):
            chat_manager.update_settings(
                model_name=model_name,
                temperature=temperature,
            )
            st.caption("✅ Настройки применены к новым сообщениям")

        st.caption(
            "Текущие значения: модель — %s, температура — %.2f"
            % (model_name, temperature)
        )

    # Основная область чата
    st.title("💬 Мой ChatGPT")
    st.caption("Базовая версия с памятью и историей чатов")

    # Получаем активный чат
    active_chat = st.session_state.active_chat
    if not active_chat or active_chat not in st.session_state.chats:
        st.error("❌ Активный чат не найден. Создайте новый чат.")
        st.stop()

    # Получаем историю текущего активного чата
    chat_history = st.session_state.chats[active_chat]["messages"]

    # ============================================
    # Счётчик токенов (верхняя панель)
    # ============================================
    current_settings = chat_manager.get_current_settings()
    model_name = current_settings.get("model_name", "gpt-3.5-turbo")

    # Подсчитываем общее количество токенов
    total_tokens = calculate_total_tokens(chat_history, model_name)

    # Инициализируем счётчик в session_state
    if "total_tokens" not in st.session_state:
        st.session_state.total_tokens = total_tokens
    else:
        st.session_state.total_tokens = total_tokens

    # Отображаем счётчик токенов с красивым оформлением
    st.markdown(
        f"<div style='text-align:center; color:#666; font-size:0.9em; "
        f"padding:10px; background-color:#f0f2f6; border-radius:5px; "
        f"margin-bottom:15px;'>"
        f"🔢 <b>Токены в текущем чате:</b> {st.session_state.total_tokens}"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ============================================
    # Отображение истории текущего чата
    # ============================================

    # Отображаем историю с временными метками
    for message in chat_history:
        role = message["role"]
        content = message["content"]

        with st.chat_message(role):
            st.write(content)
            # Добавляем временную метку под каждым сообщением
            timestamp = format_timestamp()
            st.markdown(
                f"<div style='font-size:0.75em; color:#999; "
                f"text-align:right; margin-top:-10px;'>{timestamp}</div>",
                unsafe_allow_html=True,
            )

    # Проверяем, был ли выбран быстрый промпт
    # Если да, показываем текстовое поле для редактирования
    default_value = st.session_state.get("prompt_input", "")

    if default_value:
        # Режим редактирования быстрого промпта
        # Показываем текстовое поле с предзаполненным шаблоном
        st.info("✏️ Отредактируйте шаблон и нажмите Enter для отправки")

        prompt = st.text_area(
            "Ваше сообщение:",
            value=default_value,
            height=120,
            key="prompt_edit_field",
        )

        # Кнопки для отправки или отмены
        col1, col2 = st.columns([1, 1])

        with col1:
            send_button = st.button(
                "📤 Отправить",
                use_container_width=True,
                type="primary",
            )

        with col2:
            cancel_button = st.button(
                "❌ Отмена",
                use_container_width=True,
            )

        # Обработка нажатия кнопок
        if cancel_button:
            # Отменяем — очищаем предзаполненное значение
            st.session_state["prompt_input"] = ""
            st.rerun()

        if send_button and prompt.strip():
            # Очищаем предзаполненное значение
            st.session_state["prompt_input"] = ""

            # Добавляем сообщение пользователя в историю
            st.session_state.chats[active_chat]["messages"].append(
                {"role": "user", "content": prompt}
            )

            # Отображаем сообщение пользователя с временной меткой
            with st.chat_message("user"):
                st.write(prompt)
                timestamp = format_timestamp()
                st.markdown(
                    f"<div style='font-size:0.75em; color:#999; "
                    f"text-align:right; margin-top:-10px;'>{timestamp}</div>",
                    unsafe_allow_html=True,
                )

            # Создаём placeholder для индикатора "Печатает..."
            typing_placeholder = st.empty()

            # Получаем и отображаем ответ
            with st.chat_message("assistant"):
                # Показываем индикатор "Печатает..." в placeholder
                with typing_placeholder.container():
                    show_typing_indicator(typing_placeholder, duration=1.5)

                # Получаем правила общения из состояния
                chat_rules = st.session_state.get("chat_rules", "").strip()

                # Если правила заданы, добавляем их к сообщению
                if chat_rules:
                    # Формируем расширенный промпт с правилами
                    enhanced_prompt = (
                        f"[Инструкции для ответа: {chat_rules}]\n\n"
                        f"Вопрос пользователя: {prompt}"
                    )
                    # Используем новый метод без сохранения в файл
                    response = chat_manager.generate_response(
                        enhanced_prompt,
                        st.session_state.chats[active_chat]["messages"][:-1],
                    )
                else:
                    # Отправляем сообщение без правил
                    response = chat_manager.generate_response(
                        prompt, st.session_state.chats[active_chat]["messages"][:-1]
                    )

                # Добавляем ответ AI в историю
                st.session_state.chats[active_chat]["messages"].append(
                    {"role": "assistant", "content": response}
                )

                # Очищаем индикатор "Печатает..."
                typing_placeholder.empty()

                # Отображаем ответ с временной меткой
                st.write(response)
                timestamp = format_timestamp()
                st.markdown(
                    f"<div style='font-size:0.75em; color:#999; "
                    f"text-align:right; margin-top:-10px;'>{timestamp}</div>",
                    unsafe_allow_html=True,
                )
            st.rerun()
    else:
        # Обычный режим — стандартное поле ввода чата
        prompt = st.chat_input("Введите ваше сообщение...")

        if prompt:
            # Добавляем сообщение пользователя в историю
            st.session_state.chats[active_chat]["messages"].append(
                {"role": "user", "content": prompt}
            )

            # Отображаем сообщение пользователя с временной меткой
            with st.chat_message("user"):
                st.write(prompt)
                timestamp = format_timestamp()
                st.markdown(
                    f"<div style='font-size:0.75em; color:#999; "
                    f"text-align:right; margin-top:-10px;'>{timestamp}</div>",
                    unsafe_allow_html=True,
                )

            # Создаём placeholder для индикатора "Печатает..."
            typing_placeholder = st.empty()

            # Получаем и отображаем ответ
            with st.chat_message("assistant"):
                # Показываем индикатор "Печатает..." в placeholder
                with typing_placeholder.container():
                    show_typing_indicator(typing_placeholder, duration=1.5)

                # Получаем правила общения из состояния
                chat_rules = st.session_state.get("chat_rules", "").strip()

                # Если правила заданы, добавляем их к сообщению
                if chat_rules:
                    # Формируем расширенный промпт с правилами
                    enhanced_prompt = (
                        f"[Инструкции для ответа: {chat_rules}]\n\n"
                        f"Вопрос пользователя: {prompt}"
                    )
                    # Используем новый метод без сохранения в файл
                    response = chat_manager.generate_response(
                        enhanced_prompt,
                        st.session_state.chats[active_chat]["messages"][:-1],
                    )
                else:
                    # Отправляем сообщение без правил
                    response = chat_manager.generate_response(
                        prompt, st.session_state.chats[active_chat]["messages"][:-1]
                    )

                # Добавляем ответ AI в историю
                st.session_state.chats[active_chat]["messages"].append(
                    {"role": "assistant", "content": response}
                )

                # Очищаем индикатор "Печатает..."
                typing_placeholder.empty()

                # Отображаем ответ с временной меткой
                st.write(response)
                timestamp = format_timestamp()
                st.markdown(
                    f"<div style='font-size:0.75em; color:#999; "
                    f"text-align:right; margin-top:-10px;'>{timestamp}</div>",
                    unsafe_allow_html=True,
                )
            st.rerun()


if __name__ == "__main__":
    main()

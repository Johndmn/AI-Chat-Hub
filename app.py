import uuid

import streamlit as st

from src.chat_manager import ChatManager

# Настройка страницы
st.set_page_config(
    page_title="AI Tutor Chat",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Инициализация менеджера чатов
@st.cache_resource
def get_chat_manager():
    return ChatManager()


chat_manager = get_chat_manager()


def main():
    # Сайдбар
    with st.sidebar:
        st.title("💬 Настройки чата")

        # Кнопка нового чата
        if st.button("🆕 Новый чат", use_container_width=True):
            new_session_id = f"chat_{uuid.uuid4().hex[:8]}"
            chat_manager.start_new_chat(new_session_id)
            st.rerun()

        st.divider()

        # История чатов
        st.subheader("История чатов")
        sessions = chat_manager.get_sessions()

        if not sessions:
            st.info("Пока нет активных чатов")

        # Инициализируем состояние для подтверждения удаления
        if "delete_confirm" not in st.session_state:
            st.session_state["delete_confirm"] = None

        # Обработка подтверждённого удаления
        if st.session_state.get("delete_confirm"):
            delete_id = st.session_state["delete_confirm"]
            # Удаляем чат через менеджер
            if chat_manager.delete_session(delete_id):
                # Проверяем, остались ли ещё чаты
                remaining_sessions = chat_manager.get_sessions()
                if not remaining_sessions:
                    # Если все чаты удалены, создаём новый
                    new_session_id = f"chat_{uuid.uuid4().hex[:8]}"
                    chat_manager.start_new_chat(new_session_id)
                    st.session_state["delete_feedback"] = (
                        "✅ Чат удалён. Создан новый чат."
                    )
                else:
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
        for session in sessions:
            session_id = session["session_id"]
            title = session["title"]
            message_count = session["message_count"]

            # Формируем метку с количеством сообщений
            if message_count:
                label = f"💬 {title} ({message_count})"
            else:
                label = f"💬 {title}"

            button_type = "primary" if session["is_current"] else "secondary"

            # Используем columns с фиксированным соотношением для стабильности
            # col1 (85%) — основная кнопка чата, растягивается на всю ширину
            # col2 (15%) — кнопка удаления фиксированного размера
            # Такое соотношение предотвращает смещение иконки при ресайзе
            col1, col2 = st.columns([0.85, 0.15], gap="small")

            with col1:
                # Кнопка переключения на чат
                # use_container_width=True делает кнопку адаптивной
                # Она заполняет всю доступную ширину первой колонки
                if st.button(
                    label,
                    key=f"session_btn_{session_id}",
                    use_container_width=True,
                    type=button_type,
                ):
                    chat_manager.switch_session(session_id)
                    st.rerun()

            with col2:
                # Кнопка удаления для всех чатов
                # Фиксированная ширина колонки (15%) гарантирует, что иконка
                # остаётся на одном месте относительно правого края
                # При изменении ширины sidebar обе колонки масштабируются
                # пропорционально, сохраняя горизонтальное выравнивание
                if st.button(
                    "🗑️",
                    key=f"delete_btn_{session_id}",
                    help="Удалить чат",
                    use_container_width=True,
                ):
                    # Сохраняем ID чата для подтверждения
                    st.session_state["pending_delete"] = session_id
                    st.rerun()

        # Модальное окно подтверждения удаления
        if st.session_state.get("pending_delete"):
            pending_id = st.session_state["pending_delete"]
            # Находим название чата для подтверждения
            pending_title = next(
                (s["title"] for s in sessions if s["session_id"] == pending_id),
                pending_id,
            )

            st.warning(
                f"⚠️ Вы уверены, что хотите удалить чат "
                f'"{pending_title}"? Это действие нельзя отменить.'
            )

            # Кнопки подтверждения
            confirm_col1, confirm_col2 = st.columns(2)

            with confirm_col1:
                if st.button(
                    "✅ Да, удалить",
                    key="confirm_delete",
                    type="primary",
                    use_container_width=True,
                ):
                    # Подтверждаем удаление
                    st.session_state["delete_confirm"] = pending_id
                    st.session_state.pop("pending_delete", None)
                    st.rerun()

            with confirm_col2:
                if st.button(
                    "❌ Отмена",
                    key="cancel_delete",
                    use_container_width=True,
                ):
                    # Отменяем удаление
                    st.session_state.pop("pending_delete", None)
                    st.rerun()

        current_info = chat_manager.get_session_info()
        session_id = current_info["session_id"]
        base_key = f"session_title_{session_id}"
        state_key = f"{base_key}_state"
        widget_key = f"{base_key}_input"
        version_key = f"{base_key}_version"
        pending_key = "pending_title_override"

        pending_override = st.session_state.pop(pending_key, None)
        if pending_override and pending_override.get("session_id") == session_id:
            st.session_state[state_key] = pending_override.get("title", "")
            st.session_state[version_key] = pending_override.get("version", 0)
            st.session_state[widget_key] = pending_override.get("title", "")
            st.session_state["rename_feedback"] = pending_override.get(
                "feedback",
                "✅ Название чата обновлено",
            )

        if (
            state_key not in st.session_state
            or st.session_state.get(version_key) != current_info["title_version"]
        ):
            st.session_state[state_key] = current_info["title"]
            st.session_state[version_key] = current_info["title_version"]
            st.session_state[widget_key] = current_info["title"]

        new_title = st.text_input(
            "Название текущего чата",
            key=widget_key,
            max_chars=60,
            help=(
                "Введите название, чтобы легче отличать беседы."
                " По умолчанию оно обновляется после первого сообщения."
            ),
        )

        if st.button(
            "💾 Сохранить название",
            use_container_width=True,
            help="Фиксирует выбранное название за текущим чатом.",
        ):
            saved_title = chat_manager.set_session_title(
                session_id,
                new_title,
            )
            updated_info = chat_manager.get_session_info(session_id)
            st.session_state[pending_key] = {
                "session_id": session_id,
                "title": saved_title,
                "version": updated_info.get("title_version", 0),
                "feedback": "✅ Название чата обновлено",
            }
            st.rerun()

        rename_feedback = st.session_state.pop("rename_feedback", None)
        if rename_feedback:
            st.caption(rename_feedback)

        st.divider()

        # Экспорт чата
        st.subheader("Экспорт")

        # Получаем историю текущего чата
        chat_history = chat_manager.get_chat_history()

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
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            chat_title = current_info.get("title", "chat")
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

        # Быстрые промпты
        st.subheader("Быстрые промпты")

        # Инициализируем состояние для поля ввода
        if "prompt_input" not in st.session_state:
            st.session_state["prompt_input"] = ""

        # Словарь с шаблонами промптов
        # Каждый ключ — название промпта, значение — текст шаблона
        prompt_templates = {
            "essay": "Напиши подробное эссе на тему: ",
            "explain": "Объясни следующий код:\n```\n[вставь код здесь]\n```",
            "summarize": "Кратко резюмируй следующий текст:\n",
        }

        # Создаём три колонки для кнопок быстрых промптов
        col1, col2, col3 = st.columns(3)

        with col1:
            # Кнопка "Написать эссе"
            if st.button(
                "✍️",
                key="prompt_essay",
                help="Написать эссе",
                use_container_width=True,
            ):
                # Вставляем шаблон в поле ввода
                st.session_state["prompt_input"] = prompt_templates["essay"]
                st.rerun()

        with col2:
            # Кнопка "Объяснить код"
            if st.button(
                "🔍",
                key="prompt_explain",
                help="Объяснить код",
                use_container_width=True,
            ):
                # Вставляем шаблон в поле ввода
                st.session_state["prompt_input"] = prompt_templates["explain"]
                st.rerun()

        with col3:
            # Кнопка "Резюмировать"
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

    # Отображение истории текущего чата
    chat_history = chat_manager.get_chat_history()

    for message in chat_history:
        with st.chat_message(message["role"]):
            st.write(message["content"])

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

            # Отображаем сообщение пользователя
            with st.chat_message("user"):
                st.write(prompt)

            # Получаем и отображаем ответ
            with st.chat_message("assistant"):
                with st.spinner("Думаю..."):
                    # Получаем правила общения из состояния
                    chat_rules = st.session_state.get("chat_rules", "").strip()

                    # Если правила заданы, добавляем их к сообщению
                    if chat_rules:
                        # Формируем расширенный промпт с правилами
                        enhanced_prompt = (
                            f"[Инструкции для ответа: {chat_rules}]\n\n"
                            f"Вопрос пользователя: {prompt}"
                        )
                        response = chat_manager.send_message(enhanced_prompt)
                    else:
                        # Отправляем сообщение без правил
                        response = chat_manager.send_message(prompt)

                    st.write(response)
            st.rerun()
    else:
        # Обычный режим — стандартное поле ввода чата
        prompt = st.chat_input("Введите ваше сообщение...")

        if prompt:
            # Отображаем сообщение пользователя
            with st.chat_message("user"):
                st.write(prompt)

            # Получаем и отображаем ответ
            with st.chat_message("assistant"):
                with st.spinner("Думаю..."):
                    # Получаем правила общения из состояния
                    chat_rules = st.session_state.get("chat_rules", "").strip()

                    # Если правила заданы, добавляем их к сообщению
                    if chat_rules:
                        # Формируем расширенный промпт с правилами
                        enhanced_prompt = (
                            f"[Инструкции для ответа: {chat_rules}]\n\n"
                            f"Вопрос пользователя: {prompt}"
                        )
                        response = chat_manager.send_message(enhanced_prompt)
                    else:
                        # Отправляем сообщение без правил
                        response = chat_manager.send_message(prompt)

                    st.write(response)


if __name__ == "__main__":
    main()

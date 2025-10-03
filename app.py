import streamlit as st
from src.chat_manager import ChatManager
import uuid

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

        for session in sessions:
            session_id = session["session_id"]
            title = session["title"]
            message_count = session["message_count"]
            if message_count:
                label = f"💬 {title} ({message_count})"
            else:
                label = f"💬 {title}"
            button_type = "primary" if session["is_current"] else "secondary"

            if st.button(
                label,
                key=f"session_btn_{session_id}",
                use_container_width=True,
                type=button_type,
            ):
                chat_manager.switch_session(session_id)
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

    # Поле ввода сообщения
    if prompt := st.chat_input("Введите ваше сообщение..."):
        # Отображаем сообщение пользователя
        with st.chat_message("user"):
            st.write(prompt)

        # Получаем и отображаем ответ
        with st.chat_message("assistant"):
            with st.spinner("Думаю..."):
                response = chat_manager.send_message(prompt)
                st.write(response)


if __name__ == "__main__":
    main()

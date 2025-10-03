import streamlit as st
from src.chat_manager import ChatManager
import uuid

# Настройка страницы
st.set_page_config(
    page_title="AI Tutor Chat",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
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
        sessions = chat_manager.get_all_sessions()
        
        for session in sessions:
            session_name = session if session != "default" else "Главный чат"
            if st.button(
                f"💬 {session_name}", 
                key=session,
                use_container_width=True,
                type="primary" if session == chat_manager.current_session_id else "secondary"
            ):
                chat_manager.current_session_id = session
                st.rerun()
        
        st.divider()
        
        # Настройки
        st.subheader("Настройки")
        st.info("Температура: 0.7")
        st.info("Модель: GPT-3.5 Turbo")

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
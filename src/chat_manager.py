from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, AIMessage
from langchain.memory import ConversationBufferMemory
from src.config import get_config

class ChatManager:
    def __init__(self):
        self.config = get_config()
        self.llm = ChatOpenAI(
            model_name=self.config.MODEL_NAME,
            openai_api_key=self.config.OPENAI_API_KEY,
            temperature=0.7
        )
        self.memory = ConversationBufferMemory(return_messages=True)
        self.chat_sessions = {}  # Хранение разных чатов
        self.current_session_id = "default"

    def start_new_chat(self, session_id=None):
        """Начать новый чат"""
        if session_id is None:
            session_id = f"session_{len(self.chat_sessions) + 1}"
        
        self.chat_sessions[session_id] = {
            'memory': ConversationBufferMemory(return_messages=True),
            'history': []
        }
        self.current_session_id = session_id
        return session_id

    def get_current_session(self):
        """Получить текущую сессию чата"""
        if self.current_session_id not in self.chat_sessions:
            self.start_new_chat(self.current_session_id)
        return self.chat_sessions[self.current_session_id]

    def send_message(self, message):
        """Отправить сообщение и получить ответ"""
        session = self.get_current_session()
        
        # Добавляем сообщение пользователя в память
        session['memory'].chat_memory.add_user_message(message)
        session['history'].append({"role": "user", "content": message})
        
        # Получаем историю для контекста
        history = session['memory'].load_memory_variables({})['history']
        
        # Создаем промпт с историей
        messages = history + [HumanMessage(content=message)]
        
        # Получаем ответ от модели
        response = self.llm.invoke(messages)
        
        # Добавляем ответ ассистента в память
        session['memory'].chat_memory.add_ai_message(response.content)
        session['history'].append({"role": "assistant", "content": response.content})
        
        return response.content

    def get_chat_history(self):
        """Получить историю текущего чата"""
        session = self.get_current_session()
        return session['history']

    def get_all_sessions(self):
        """Получить все сессии чатов"""
        return list(self.chat_sessions.keys())
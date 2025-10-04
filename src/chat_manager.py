from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage
from langchain.memory import ConversationBufferMemory

from src.config import get_config
from src.storage import ChatStorage

import logging
import uuid

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChatManager:
    def __init__(self):
        """Инициализация менеджера чатов"""
        try:
            self.config = get_config()

            # Проверим API ключ перед созданием LLM
            if not self.config.OPENAI_API_KEY:
                raise ValueError("OpenAI API ключ не установлен")

            if self.config.OPENAI_API_KEY.startswith("your_ope"):
                raise ValueError("OpenAI API ключ содержит placeholder значение")

            logger.info(
                "Используем API ключ: %s...",
                self.config.OPENAI_API_KEY[:8],
            )

            self.available_models = self.config.AVAILABLE_MODELS
            self.model_name = self.config.MODEL_NAME
            self.temperature = self.config.DEFAULT_TEMPERATURE
            self.llm = self._create_llm()
            self.memory = ConversationBufferMemory(return_messages=True)
            self.session_counter = 1
            self.chat_sessions: Dict[str, Dict[str, Any]] = {}
            self.current_session_id = "default"
            self.storage = ChatStorage()

            # Загружаем сохранённые сессии
            self._load_sessions_from_storage()

            # Создаем сессию по умолчанию если её нет
            if "default" not in self.chat_sessions:
                self.start_new_chat(
                    "default",
                    title="Главный чат",
                    custom_title=True,
                )

            logger.info("ChatManager успешно инициализирован")

        except Exception as e:
            logger.error(f"Ошибка инициализации ChatManager: {e}")
            raise

    def _create_llm(self) -> ChatOpenAI:
        """Создаем экземпляр LLM с текущими настройками"""
        return ChatOpenAI(
            model_name=self.model_name,
            openai_api_key=self.config.OPENAI_API_KEY,
            temperature=self.temperature,
        )

    def _load_sessions_from_storage(self) -> None:
        """Загружает все сохранённые сессии из хранилища"""
        try:
            saved_sessions = self.storage.load_all_sessions()

            for session_id, session_data in saved_sessions.items():
                # Восстанавливаем память из истории
                memory = ConversationBufferMemory(return_messages=True)
                for msg in session_data.get("history", []):
                    if msg.get("role") == "user":
                        memory.chat_memory.add_user_message(msg.get("content", ""))
                    elif msg.get("role") == "assistant":
                        memory.chat_memory.add_ai_message(msg.get("content", ""))

                # Восстанавливаем полную структуру сессии
                self.chat_sessions[session_id] = {
                    "memory": memory,
                    "history": session_data.get("history", []),
                    "title": session_data.get("title", session_id),
                    "custom_title": session_data.get("custom_title", False),
                    "title_version": session_data.get("title_version", 0),
                    "created_at": session_data.get("created_at"),
                }

                # Обновляем счётчик для автогенерации названий
                title = session_data.get("title", "")
                if title.startswith("Новый чат "):
                    try:
                        num = int(title.split()[-1])
                        self.session_counter = max(
                            self.session_counter,
                            num + 1,
                        )
                    except (ValueError, IndexError):
                        pass

            logger.info(
                "Загружено сессий из хранилища: %d",
                len(saved_sessions),
            )

        except Exception as e:
            logger.error("Ошибка при загрузке сессий: %s", e)

    def _save_session_to_storage(self, session_id: str) -> None:
        """Сохраняет сессию в хранилище"""
        if session_id in self.chat_sessions:
            self.storage.save_session(
                session_id,
                self.chat_sessions[session_id],
            )

    def _generate_default_title(self) -> str:
        """Создает название по умолчанию для нового чата"""
        title = f"Новый чат {self.session_counter}"
        self.session_counter += 1
        return title

    def _sanitize_title(self, title: str) -> str:
        """Приводит название чата к безопасному формату"""
        if not title:
            return "Без названия"

        cleaned = " ".join(title.strip().split())
        if len(cleaned) > 60:
            return cleaned[:60].rstrip()
        return cleaned

    def _set_session_title(
        self,
        session: Dict[str, Any],
        title: str,
        custom: bool,
    ) -> str:
        sanitized = self._sanitize_title(title)
        session["title"] = sanitized
        session["custom_title"] = custom
        session["title_version"] = session.get("title_version", 0) + 1
        return sanitized

    def set_session_title(self, session_id: str, title: str) -> str:
        """Устанавливает пользовательское название для сессии"""
        if session_id not in self.chat_sessions:
            raise ValueError(f"Сессия {session_id} не найдена")

        session = self.chat_sessions[session_id]
        sanitized = self._set_session_title(session, title, custom=True)
        self._save_session_to_storage(session_id)
        logger.info(
            "Название сессии %s обновлено: %s",
            session_id,
            sanitized,
        )
        return sanitized

    def get_session_title(self, session_id: Optional[str] = None) -> str:
        """Возвращает название указанной сессии"""
        target_id = session_id or self.current_session_id
        session = self.chat_sessions.get(target_id)
        if session is None:
            raise ValueError(f"Сессия {target_id} не найдена")
        return session.get("title") or target_id

    def get_sessions(self) -> List[Dict[str, Any]]:
        """Возвращает список сессий с метаданными"""
        sessions: List[Dict[str, Any]] = []
        for session_id, session in self.chat_sessions.items():
            sessions.append(
                {
                    "session_id": session_id,
                    "title": session.get("title") or session_id,
                    "message_count": len(session.get("history", [])),
                    "is_current": session_id == self.current_session_id,
                    "created_at": session.get("created_at"),
                    "title_version": session.get("title_version", 0),
                }
            )
        return sessions

    def _title_from_message(self, message: str) -> str:
        """Создает название на основе первого пользовательского сообщения"""
        sanitized = self._sanitize_title(message)
        if len(sanitized) > 45:
            return f"{sanitized[:45].rstrip()}…"
        return sanitized

    def _maybe_update_auto_title(
        self,
        session: Dict[str, Any],
        message: str,
    ) -> None:
        if session.get("custom_title"):
            return

        user_messages = [
            item for item in session.get("history", []) if item.get("role") == "user"
        ]
        if len(user_messages) != 1:
            return

        auto_title = self._title_from_message(message)
        self._set_session_title(session, auto_title, custom=False)

    def update_settings(
        self,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> bool:
        """Обновить настройки модели и температуры"""
        try:
            changed = False

            if model_name is not None and model_name != self.model_name:
                if model_name not in self.available_models:
                    raise ValueError(f"Модель {model_name} не поддерживается")
                self.model_name = model_name
                changed = True

            if temperature is not None and temperature != self.temperature:
                if not 0.0 <= temperature <= 1.0:
                    raise ValueError("Температура должна быть в диапазоне 0-1")
                self.temperature = float(temperature)
                changed = True

            if changed:
                self.llm = self._create_llm()
                logger.info(
                    "Настройки обновлены: модель=%s, температура=%.2f",
                    self.model_name,
                    self.temperature,
                )
            return changed

        except Exception as exc:
            logger.error("Не удалось обновить настройки: %s", exc)
            raise

    def get_current_settings(self) -> Dict[str, Any]:
        """Возвращает текущие настройки модели"""
        return {
            "model_name": self.model_name,
            "temperature": self.temperature,
            "available_models": self.available_models,
        }

    def reset_settings(self) -> None:
        """Сбрасывает настройки модели к значениям по умолчанию"""
        self.model_name = self.config.MODEL_NAME
        self.temperature = self.config.DEFAULT_TEMPERATURE
        self.llm = self._create_llm()
        logger.info(
            "Настройки сброшены: модель=%s, температура=%.2f",
            self.model_name,
            self.temperature,
        )

    def start_new_chat(
        self,
        session_id: Optional[str] = None,
        title: Optional[str] = None,
        custom_title: Optional[bool] = None,
    ) -> str:
        """Начать новый чат"""
        try:
            if session_id is None:
                session_id = f"chat_{uuid.uuid4().hex[:8]}"

            session_data: Dict[str, Any] = {
                "memory": ConversationBufferMemory(return_messages=True),
                "history": [],
                "created_at": datetime.utcnow(),
                "title": "",
                "custom_title": False,
                "title_version": 0,
            }

            assigned_title = title or self._generate_default_title()
            custom_flag = custom_title if custom_title is not None else bool(title)
            self._set_session_title(session_data, assigned_title, custom_flag)

            self.chat_sessions[session_id] = session_data
            self.current_session_id = session_id
            self._save_session_to_storage(session_id)

            logger.info("Создана новая сессия: %s", session_id)
            return session_id

        except Exception as e:
            logger.error("Ошибка при создании новой сессии: %s", e)
            raise

    def get_current_session(self) -> Dict[str, Any]:
        """Получить текущую сессию чата"""
        if self.current_session_id not in self.chat_sessions:
            logger.warning(
                f"Сессия {self.current_session_id} не найдена, создаем новую"
            )
            self.start_new_chat(self.current_session_id)
        return self.chat_sessions[self.current_session_id]

    def send_message(self, message: str) -> str:
        """Отправить сообщение и получить ответ"""
        if not message or not message.strip():
            return "Сообщение не может быть пустым"

        try:
            session = self.get_current_session()

            # Добавляем сообщение пользователя в память
            session["memory"].chat_memory.add_user_message(message)
            session["history"].append({"role": "user", "content": message})
            self._maybe_update_auto_title(session, message)

            # Получаем историю для контекста
            history = session["memory"].load_memory_variables({})["history"]

            # Создаем промпт с историей
            messages = history + [HumanMessage(content=message)]

            # Получаем ответ от модели
            response = self.llm.invoke(messages)

            # Добавляем ответ ассистента в память
            session["memory"].chat_memory.add_ai_message(response.content)
            session["history"].append(
                {"role": "assistant", "content": response.content}
            )

            logger.info(
                "Сообщение обработано для сессии %s",
                self.current_session_id,
            )
            self._save_session_to_storage(self.current_session_id)
            return response.content

        except Exception as e:
            error_msg = f"Ошибка при отправке сообщения: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def get_chat_history(
        self, session_id: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """Получить историю чата"""
        try:
            if session_id is None:
                session_id = self.current_session_id

            if session_id in self.chat_sessions:
                return self.chat_sessions[session_id]["history"]
            else:
                logger.warning(f"Сессия {session_id} не найдена")
                return []

        except Exception as e:
            logger.error(f"Ошибка при получении истории: {e}")
            return []

    def get_all_sessions(self) -> List[str]:
        """Получить все сессии чатов"""
        return [item["session_id"] for item in self.get_sessions()]

    def switch_session(self, session_id: str) -> bool:
        """Переключиться на другую сессию"""
        try:
            if session_id in self.chat_sessions:
                self.current_session_id = session_id
                logger.info(f"Переключены на сессию: {session_id}")
                return True
            else:
                logger.warning(f"Сессия {session_id} не найдена")
                return False
        except Exception as e:
            logger.error(f"Ошибка при переключении сессии: {e}")
            return False

    def delete_session(self, session_id: str) -> bool:
        """Удалить сессию чата"""
        try:
            if session_id in self.chat_sessions:
                del self.chat_sessions[session_id]
                self.storage.delete_session(session_id)

                # Если удаляем текущую сессию, переключаемся на другую
                if self.current_session_id == session_id:
                    # Находим любую оставшуюся сессию
                    remaining = list(self.chat_sessions.keys())
                    if remaining:
                        self.current_session_id = remaining[0]
                    else:
                        # Если это была последняя сессия, обнуляем ID
                        self.current_session_id = None

                logger.info(f"Сессия {session_id} удалена")
                return True
            else:
                logger.warning(f"Сессия {session_id} не найдена для удаления")
                return False

        except Exception as e:
            logger.error(f"Ошибка при удалении сессии: {e}")
            return False

    def clear_current_chat(self) -> bool:
        """Очистить историю текущего чата"""
        try:
            session = self.get_current_session()
            session["memory"].clear()
            session["history"] = []
            self._save_session_to_storage(self.current_session_id)

            logger.info(f"История сессии {self.current_session_id} очищена")
            return True

        except Exception as e:
            logger.error(f"Ошибка при очистке чата: {e}")
            return False

    def get_session_info(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Получить информацию о сессии"""
        try:
            if session_id is None:
                session_id = self.current_session_id

            if session_id in self.chat_sessions:
                session = self.chat_sessions[session_id]
                history = session["history"]

                return {
                    "session_id": session_id,
                    "message_count": len(history),
                    "last_message": history[-1] if history else None,
                    "is_current": session_id == self.current_session_id,
                    "title": session.get("title") or session_id,
                    "custom_title": session.get("custom_title", False),
                    "title_version": session.get("title_version", 0),
                    "created_at": session.get("created_at"),
                }
            else:
                return {"error": f"Сессия {session_id} не найдена"}

        except Exception as e:
            logger.error(f"Ошибка при получении информации о сессии: {e}")
            return {"error": str(e)}

    def rename_session(self, old_session_id: str, new_session_id: str) -> bool:
        """Переименовать сессию"""
        try:
            if old_session_id not in self.chat_sessions:
                logger.warning(f"Сессия {old_session_id} не найдена")
                return False

            if new_session_id in self.chat_sessions:
                logger.warning(f"Сессия {new_session_id} уже существует")
                return False

            # Перемещаем данные в новую сессию
            self.chat_sessions[new_session_id] = self.chat_sessions.pop(old_session_id)

            # Обновляем текущую сессию если нужно
            if self.current_session_id == old_session_id:
                self.current_session_id = new_session_id

            self._save_session_to_storage(new_session_id)
            self.storage.delete_session(old_session_id)

            logger.info(
                "Сессия %s переименована в %s",
                old_session_id,
                new_session_id,
            )
            return True

        except Exception as e:
            logger.error(f"Ошибка при переименовании сессии: {e}")
            return False


# Пример использования
if __name__ == "__main__":
    try:
        chat_manager = ChatManager()

        # Тестирование основных функций
        print("Сессии:", chat_manager.get_all_sessions())

        # Создание новой сессии
        new_session = chat_manager.start_new_chat()
        print("Новая сессия:", new_session)

        # Отправка сообщения
        response = chat_manager.send_message("Привет! Как дела?")
        print("Ответ:", response)

        # Получение истории
        history = chat_manager.get_chat_history()
        print("История:", history)

        # Информация о сессии
        info = chat_manager.get_session_info()
        print("Информация о сессии:", info)

    except Exception as e:
        print(f"Ошибка при тестировании: {e}")

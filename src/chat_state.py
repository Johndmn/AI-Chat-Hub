"""
Модуль управления состоянием чатов пользователя (src/chat_state.py).

Отвечает за:
1. Изолированное хранение чатов каждого пользователя в рамках его сессии
   (st.session_state), чтобы 5–10+ одновременных посетителей сайта
   никогда не видели чужие переписки и API-ключи.
2. Создание, переключение, переименование и безопасное удаление чатов.
3. Сохранение реального времени отправки каждого сообщения (исправление бага
   с перезаписью времени при перерисовке страницы).
4. Автоматическое именование нового чата по первому вопросу пользователя.
5. Формирование текстового файла для экспорта истории диалога (.txt).
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, MutableMapping, Optional, Tuple


class ChatSessionManager:
    """
    Менеджер пользовательской сессии чатов.

    Работает поверх любого словареподобного хранилища (st.session_state в браузере
    или обычного dict в модульных тестах), обеспечивая полную изоляцию между
    параллельными пользователями.
    """

    def __init__(
        self,
        state: MutableMapping[str, Any],
        default_demo_enabled: bool = False,
        default_temperature: float = 0.7,
    ):
        self.state = state
        self._ensure_initialized(
            default_demo_enabled=default_demo_enabled,
            default_temperature=default_temperature,
        )

    def _ensure_initialized(
        self,
        default_demo_enabled: bool,
        default_temperature: float,
    ) -> None:
        """Инициализирует ключи сессии при первом входе пользователя."""
        # Режим доступа к API: "demo" (бесплатный встроенный) или "byok" (свой ключ)
        if "auth_mode" not in self.state:
            self.state["auth_mode"] = "demo" if default_demo_enabled else "byok"

        # Настройки BYOK (хранятся только в оперативной памяти вкладки пользователя)
        self.state.setdefault("provider_id", "openrouter")
        self.state.setdefault("api_key", "")
        self.state.setdefault("custom_base_url", "")
        self.state.setdefault("custom_model_name", "")
        self.state.setdefault("selected_model", "")
        self.state.setdefault("demo_model_override", "")
        self.state.setdefault("fetched_models", {})
        self.state.setdefault("temperature", float(default_temperature))

        # Счётчик использованных демо-запросов в текущей сессии
        self.state.setdefault("demo_session_used", 0)

        # Правила общения (System Prompt) и черновик быстрого промпта
        self.state.setdefault("chat_rules", "")
        self.state.setdefault("prompt_input", "")

        # Режим рабочего пространства (chat / jira)
        self.state.setdefault("workspace_mode", "chat")

        # Прикреплённый файл в режиме чата
        self.state.setdefault("attached_file_name", "")
        self.state.setdefault("attached_file_tokens", 0)
        self.state.setdefault("attached_file_fragment", "")

        # Состояния подтверждения удаления и уведомлений
        self.state.setdefault("pending_delete", None)
        self.state.setdefault("feedback_message", None)

        # Словарь всех чатов пользователя
        if "chats" not in self.state or not self.state["chats"]:
            self.state["chat_counter"] = 1
            first_id = self.create_chat(title="Новый чат 1", custom_title=False)
            self.state["active_chat"] = first_id

        if (
            "active_chat" not in self.state
            or self.state["active_chat"] not in self.state["chats"]
        ):
            self.state["active_chat"] = next(iter(self.state["chats"].keys()))

    @property
    def chats(self) -> Dict[str, Dict[str, Any]]:
        """Возвращает словарь всех чатов текущего пользователя."""
        return self.state["chats"]

    @property
    def active_chat_id(self) -> str:
        """Возвращает идентификатор текущего открытого чата."""
        return self.state["active_chat"]

    @property
    def active_chat(self) -> Dict[str, Any]:
        """Возвращает объект текущего активного чата."""
        return self.chats[self.active_chat_id]

    def create_chat(
        self,
        title: Optional[str] = None,
        custom_title: bool = False,
    ) -> str:
        """Создаёт новую беседу и делает её активной."""
        if "chats" not in self.state:
            self.state["chats"] = {}
        counter = int(self.state.get("chat_counter", 1))

        chat_id = f"chat_{uuid.uuid4().hex[:8]}"
        assigned_title = (title or f"Новый чат {counter}").strip()
        if not title:
            self.state["chat_counter"] = counter + 1

        self.state["chats"][chat_id] = {
            "title": assigned_title,
            "custom_title": custom_title,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "messages": [],
        }
        self.state["active_chat"] = chat_id
        return chat_id

    def switch_chat(self, chat_id: str) -> bool:
        """Переключает пользователя на выбранный чат."""
        if chat_id in self.chats:
            self.state["active_chat"] = chat_id
            return True
        return False

    def rename_active_chat(self, new_title: str) -> bool:
        """Переименовывает текущий чат и помечает название как пользовательское."""
        cleaned = " ".join((new_title or "").strip().split())
        if not cleaned:
            return False
        self.active_chat["title"] = cleaned[:60]
        self.active_chat["custom_title"] = True
        return True

    def delete_chat(self, chat_id: str) -> str:
        """
        Удаляет чат по ID. Если удалён последний чат — автоматически создаёт новый,
        чтобы интерфейс всегда оставался в рабочем состоянии.
        """
        if chat_id not in self.chats:
            return "❌ Чат для удаления не найден."

        del self.chats[chat_id]

        if not self.chats:
            self.create_chat()
            return "✅ Чат удалён. Создан новый пустой чат."

        if self.state.get("active_chat") == chat_id:
            self.state["active_chat"] = next(iter(self.chats.keys()))

        return "✅ Чат успешно удалён."

    def add_message(
        self,
        role: str,
        content: str,
        timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Добавляет сообщение в активный чат с фиксацией точного времени отправки.
        Если это первое сообщение пользователя и у чата стандартное имя ("Новый чат N"),
        автоматически даёт чату осмысленный заголовок по тексту вопроса.

        Args:
            metadata: дополнительные технические поля (например, телеметрия ответа),
                      которые не должны мешать истории переписки.
        """
        time_str = timestamp or datetime.now().strftime("%H:%M:%S")
        msg: Dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": time_str,
        }
        if metadata:
            msg["metadata"] = metadata
        chat = self.active_chat
        chat["messages"].append(msg)

        # Автозаголовок по первому сообщению пользователя
        if role == "user" and not chat.get("custom_title", False):
            user_msgs = [m for m in chat["messages"] if m.get("role") == "user"]
            if len(user_msgs) == 1:
                short_title = " ".join(content.strip().split())
                if short_title:
                    chat["title"] = (
                        f"{short_title[:38]}…" if len(short_title) > 38 else short_title
                    )

        return msg

    def export_active_chat_txt(self) -> Tuple[str, str]:
        """
        Формирует имя файла и текстовое содержимое для скачивания истории чата (.txt).
        """
        chat = self.active_chat
        title = chat.get("title", "chat")
        messages: List[Dict[str, str]] = chat.get("messages", [])

        lines: List[str] = [
            f"=== {title} ===",
            f"Дата экспорта: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        rules = str(self.state.get("chat_rules", "")).strip()
        if rules:
            lines.append(f"[Системные правила]: {rules}")
            lines.append("")

        for msg in messages:
            role_label = "Пользователь" if msg.get("role") == "user" else "AI"
            ts = msg.get("timestamp", "")
            prefix = f"[{ts}] {role_label}" if ts else role_label
            lines.append(f"{prefix}: {msg.get('content', '')}")
            lines.append("")

        export_text = "\n".join(lines)
        safe_title = "".join(
            c for c in title if c.isalnum() or c in (" ", "-", "_")
        ).strip()
        if not safe_title:
            safe_title = "chat"

        file_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_title}_{file_timestamp}.txt"
        return filename, export_text

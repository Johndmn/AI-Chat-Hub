import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ChatStorage:
    """Класс для сохранения и загрузки истории чатов на диск"""

    def __init__(self, storage_dir: str = "data/chats"):
        """
        Инициализация хранилища

        Args:
            storage_dir: Путь к директории для хранения чатов
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Хранилище чатов инициализировано: %s", self.storage_dir)

    def _get_session_path(self, session_id: str) -> Path:
        """Возвращает путь к файлу сессии"""
        return self.storage_dir / f"{session_id}.json"

    def _serialize_datetime(self, obj: Any) -> Any:
        """Сериализует datetime в ISO формат"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        return obj

    def _deserialize_datetime(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Десериализует datetime из ISO формата"""
        if "created_at" in data and isinstance(data["created_at"], str):
            try:
                data["created_at"] = datetime.fromisoformat(data["created_at"])
            except (ValueError, TypeError):
                data["created_at"] = datetime.utcnow()
        return data

    def save_session(
        self,
        session_id: str,
        session_data: Dict[str, Any],
    ) -> bool:
        """
        Сохраняет сессию на диск

        Args:
            session_id: Идентификатор сессии
            session_data: Данные сессии (без memory объекта)

        Returns:
            True если сохранение успешно, False иначе
        """
        try:
            path = self._get_session_path(session_id)

            # Подготавливаем данные для сохранения (исключаем memory)
            save_data = {
                "session_id": session_id,
                "history": session_data.get("history", []),
                "title": session_data.get("title", ""),
                "custom_title": session_data.get("custom_title", False),
                "title_version": session_data.get("title_version", 0),
                "created_at": self._serialize_datetime(
                    session_data.get("created_at", datetime.utcnow())
                ),
            }

            with open(path, "w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)

            logger.debug("Сессия %s сохранена", session_id)
            return True

        except Exception as e:
            logger.error("Ошибка при сохранении сессии %s: %s", session_id, e)
            return False

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Загружает сессию с диска

        Args:
            session_id: Идентификатор сессии

        Returns:
            Данные сессии или None если файл не найден
        """
        try:
            path = self._get_session_path(session_id)

            if not path.exists():
                logger.warning("Файл сессии %s не найден", session_id)
                return None

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            data = self._deserialize_datetime(data)
            logger.debug("Сессия %s загружена", session_id)
            return data

        except Exception as e:
            logger.error("Ошибка при загрузке сессии %s: %s", session_id, e)
            return None

    def load_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        """
        Загружает все сохранённые сессии

        Returns:
            Словарь {session_id: session_data}
        """
        sessions = {}

        try:
            for path in self.storage_dir.glob("*.json"):
                session_id = path.stem
                data = self.load_session(session_id)
                if data:
                    sessions[session_id] = data

            logger.info("Загружено сессий: %d", len(sessions))
            return sessions

        except Exception as e:
            logger.error("Ошибка при загрузке всех сессий: %s", e)
            return {}

    def delete_session(self, session_id: str) -> bool:
        """
        Удаляет сессию с диска

        Args:
            session_id: Идентификатор сессии

        Returns:
            True если удаление успешно, False иначе
        """
        try:
            path = self._get_session_path(session_id)

            if path.exists():
                path.unlink()
                logger.info("Файл сессии %s удалён", session_id)
                return True
            else:
                logger.warning(
                    "Файл сессии %s не найден для удаления",
                    session_id,
                )
                return False

        except Exception as e:
            logger.error("Ошибка при удалении сессии %s: %s", session_id, e)
            return False

    def list_sessions(self) -> List[str]:
        """
        Возвращает список идентификаторов всех сохранённых сессий

        Returns:
            Список session_id
        """
        try:
            return [path.stem for path in self.storage_dir.glob("*.json")]
        except Exception as e:
            logger.error("Ошибка при получении списка сессий: %s", e)
            return []

    def clear_all(self) -> bool:
        """
        Удаляет все сохранённые сессии

        Returns:
            True если очистка успешна, False иначе
        """
        try:
            for path in self.storage_dir.glob("*.json"):
                path.unlink()
            logger.info("Все сессии удалены")
            return True
        except Exception as e:
            logger.error("Ошибка при очистке всех сессий: %s", e)
            return False

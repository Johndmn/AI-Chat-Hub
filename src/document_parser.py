"""
Модуль извлечения текста из загруженных документов (src/document_parser.py).

Отвечает за:
1. Преобразование бинарного содержимого файлов .txt, .md, .csv, .json
   (и опционально .pdf, если установлен pypdf) в чистый текст.
2. Безопасное определение кодировки текста с fallback.
3. Подготовку сокращённой версии документа для передачи в контекст LLM
   (чтобы не переполнять окно контекста большими ТЗ).

Модуль не зависит от Streamlit — его можно покрыть unit-тестами,
передавая обычные байты и имя файла.
"""

import io
import json
from pathlib import Path
from typing import Tuple

from src.llm_service import TokenCounter

try:
    import pypdf
except ImportError:  # pragma: no cover
    pypdf = None  # type: ignore


class DocumentParserError(Exception):
    """Исключение при неподдерживаемом формате или ошибке чтения документа."""


class DocumentParser:
    """
    Утилитарный класс для извлечения текста из пользовательских файлов.

    Поддерживаемые форматы:
    - .txt, .md — обычный текст;
    - .csv — табличные данные (сохраняется как текст);
    - .json — сериализуется в читаемый JSON;
    - .pdf — только если установлен `pypdf` (опционально, без жёсткой зависимости).
    """

    SUPPORTED_EXTENSIONS: Tuple[str, ...] = (
        ".txt",
        ".md",
        ".csv",
        ".json",
        ".pdf",
    )

    @classmethod
    def is_supported(cls, filename: str) -> bool:
        """Проверяет, поддерживается ли расширение файла."""
        return Path(filename).suffix.lower() in cls.SUPPORTED_EXTENSIONS

    @staticmethod
    def _decode_text_bytes(
        file_bytes: bytes,
        encodings: Tuple[str, ...] = ("utf-8", "cp1251", "latin-1"),
    ) -> str:
        """
        Пытается декодировать текст в нескольких кодировках.
        Если ни одна не подошла — возвращает строку с заменой ошибочных символов.
        """
        for encoding in encodings:
            try:
                return file_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return file_bytes.decode("utf-8", errors="replace")

    @classmethod
    def extract_text(cls, file_bytes: bytes, filename: str) -> str:
        """
        Извлекает текст из байтов файла в зависимости от его расширения.

        Args:
            file_bytes: Сырые байты загруженного файла.
            filename: Имя файла с расширением.

        Returns:
            Строка с текстовым содержимым файла.

        Raises:
            DocumentParserError: Если формат не поддерживается или PDF не читается.
        """
        ext = Path(filename).suffix.lower()

        if ext == ".pdf":
            if pypdf is None:
                raise DocumentParserError(
                    "Для чтения PDF установите дополнительную зависимость: pip install pypdf"
                )
            return cls._extract_pdf(file_bytes)

        if ext == ".json":
            text = cls._decode_text_bytes(file_bytes)
            try:
                data = json.loads(text)
                return json.dumps(data, ensure_ascii=False, indent=2)
            except json.JSONDecodeError as exc:
                raise DocumentParserError(f"Невалидный JSON в файле: {exc}") from exc

        if ext == ".csv":
            text = cls._decode_text_bytes(file_bytes)
            # Нормализуем переносы строк и удаляем лишние \r
            return text.replace("\r\n", "\n").replace("\r", "\n")

        if ext in (".txt", ".md"):
            return cls._decode_text_bytes(file_bytes)

        raise DocumentParserError(
            f"Неподдерживаемый формат файла: {ext}. "
            f"Поддерживаются: {', '.join(cls.SUPPORTED_EXTENSIONS)}"
        )

    @classmethod
    def _extract_pdf(cls, file_bytes: bytes) -> str:
        """Извлекает текст из PDF с помощью pypdf."""
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        pages_text = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                pages_text.append(page_text)
        return "\n\n".join(pages_text)

    @classmethod
    def summarize_for_context(
        cls,
        text: str,
        max_chars: int = 6000,
        suffix: str = "\n\n[...Фрагмент документа обрезан, чтобы уместиться в контекст модели...]",
    ) -> str:
        """
        Сокращает текст до заданного лимита символов.

        Используется перед отправкой больших ТЗ в LLM, чтобы не исчерпать лимит токенов.
        """
        if not text or len(text) <= max_chars:
            return text
        return text[:max_chars] + suffix

    @classmethod
    def count_tokens(cls, text: str, model: str = "gpt-4o-mini") -> int:
        """Подсчитывает количество токенов в тексте через TokenCounter."""
        return TokenCounter.count_text_tokens(text, model=model)

    @classmethod
    def prepare_context_from_upload(
        cls,
        file_bytes: bytes,
        filename: str,
        max_chars: int = 6000,
        model: str = "gpt-4o-mini",
    ) -> Tuple[str, int, str]:
        """
        Универсальный метод: извлекает текст, считает токены и готовит сокращённый фрагмент.

        Returns:
            Кортеж (полный_текст, токены, фрагмент_для_контекста).
        """
        full_text = cls.extract_text(file_bytes, filename)
        tokens = cls.count_tokens(full_text, model=model)
        context_fragment = cls.summarize_for_context(full_text, max_chars=max_chars)
        return full_text, tokens, context_fragment

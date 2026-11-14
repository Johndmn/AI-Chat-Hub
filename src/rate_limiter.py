"""
Модуль контроля лимитов и таймера для бесплатного Демо-режима (src/rate_limiter.py).

Отвечает за:
1. Потокобезопасный (thread-safe) учёт общего дневного лимита запросов
   для всех пользователей приложения одновременно (при работе 5–10+ человек).
2. Учёт индивидуального лимита запросов на одну пользовательскую сессию.
3. Обработку ситуации, когда внешний бесплатный провайдер вернул ошибку 429
   (RateLimitError) — включает таймер обратного отсчёта до восстановления
   и предлагает пользователю ввести собственный API-ключ (BYOK).
"""

import threading
import time
from dataclasses import dataclass
from typing import Optional


def format_countdown(seconds: float) -> str:
    """
    Форматирует оставшееся время в секундах в человекочитаемый таймер:
    например: '03 ч. 24 мин. 15 сек.' или '12 мин. 05 сек.'
    """
    total_sec = max(0, int(seconds))
    hours, remainder = divmod(total_sec, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours > 0:
        return f"{hours:02d} ч. {minutes:02d} мин. {secs:02d} сек."
    return f"{minutes:02d} мин. {secs:02d} сек."


@dataclass(frozen=True)
class RateLimitStatus:
    """
    Результат проверки доступности бесплатного Демо-режима.
    Используется UI-слоем для отображения остатка запросов или баннера с таймером.
    """

    allowed: bool
    reason: str
    remaining_global: int
    remaining_session: int
    reset_seconds: int

    @property
    def formatted_timer(self) -> str:
        """Возвращает строку таймера обратного отсчёта до сброса лимита."""
        return format_countdown(self.reset_seconds)


class DemoRateLimiter:
    """
    Потокобезопасный контроллер лимитов бесплатного API.

    При деплое на Streamlit Cloud или обычный сервер экземпляр этого класса
    кэшируется через @st.cache_resource, поэтому все подключённые пользователи
    (например, 5–10 одновременных посетителей) безопасно разделяют общий счётчик
    через мьютекс (threading.Lock).
    """

    WINDOW_SECONDS = 24 * 3600  # 24 часа (суточное окно сброса)

    def __init__(self, daily_global_limit: int = 100, session_limit: int = 15):
        self.daily_global_limit = max(1, daily_global_limit)
        self.session_limit = max(1, session_limit)

        self._lock = threading.Lock()
        self._window_start: float = time.time()
        self._global_used: int = 0
        self._upstream_cooldown_until: float = 0.0

    def _refresh_window_unlocked(self, now: float) -> None:
        """
        Сбрасывает суточный счётчик, если с начала окна прошло больше 24 часов.
        Вызывается только внутри блока `with self._lock`.
        """
        if now - self._window_start >= self.WINDOW_SECONDS:
            self._window_start = now
            self._global_used = 0
            self._upstream_cooldown_until = 0.0

    def check_status(self, session_used: int = 0) -> RateLimitStatus:
        """
        Проверяет, можно ли выполнить запрос в бесплатном демо-режиме,
        не изменяя счётчики.
        """
        now = time.time()
        with self._lock:
            self._refresh_window_unlocked(now)

            window_reset_sec = max(
                1, int(self.WINDOW_SECONDS - (now - self._window_start))
            )
            remaining_global = max(0, self.daily_global_limit - self._global_used)
            remaining_session = max(0, self.session_limit - session_used)

            # 1. Проверяем, не заблокирован ли внешний бесплатный API из-за 429
            if now < self._upstream_cooldown_until:
                cooldown_sec = max(1, int(self._upstream_cooldown_until - now))
                return RateLimitStatus(
                    allowed=False,
                    reason=(
                        "Внешний бесплатный API временно перегружен или исчерпал "
                        "лимит провайдера для всех пользователей."
                    ),
                    remaining_global=remaining_global,
                    remaining_session=remaining_session,
                    reset_seconds=cooldown_sec,
                )

            # 2. Проверяем общий дневной лимит для всех посетителей
            if remaining_global <= 0:
                return RateLimitStatus(
                    allowed=False,
                    reason=(
                        "Бесплатный дневной лимит для всех пользователей превышен. "
                        "Пожалуйста, введите свой API-ключ (BYOK), чтобы продолжить."
                    ),
                    remaining_global=0,
                    remaining_session=remaining_session,
                    reset_seconds=window_reset_sec,
                )

            # 3. Проверяем лимит текущей пользовательской сессии
            if remaining_session <= 0:
                return RateLimitStatus(
                    allowed=False,
                    reason=(
                        f"Исчерпан лимит демо-запросов для вашей сессии ({self.session_limit} шт.). "
                        "Подключите собственный API-ключ в панели слева для работы без ограничений."
                    ),
                    remaining_global=remaining_global,
                    remaining_session=0,
                    reset_seconds=window_reset_sec,
                )

            return RateLimitStatus(
                allowed=True,
                reason="OK",
                remaining_global=remaining_global,
                remaining_session=remaining_session,
                reset_seconds=window_reset_sec,
            )

    def consume(self, session_used: int = 0) -> RateLimitStatus:
        """
        Атомарно проверяет лимит и (если разрешено) списывает 1 запрос из общего пула.
        Гарантирует отсутствие состояния гонки (race condition), когда 5–10 человек
        отправляют сообщение в одну и ту же миллисекунду.
        """
        now = time.time()
        with self._lock:
            self._refresh_window_unlocked(now)

            window_reset_sec = max(
                1, int(self.WINDOW_SECONDS - (now - self._window_start))
            )
            remaining_global = max(0, self.daily_global_limit - self._global_used)
            remaining_session = max(0, self.session_limit - session_used)

            if now < self._upstream_cooldown_until:
                cooldown_sec = max(1, int(self._upstream_cooldown_until - now))
                return RateLimitStatus(
                    allowed=False,
                    reason=(
                        "Бесплатный API провайдера временно исчерпал лимит запросов. "
                        "Пожалуйста, введите свой API-ключ (BYOK)."
                    ),
                    remaining_global=remaining_global,
                    remaining_session=remaining_session,
                    reset_seconds=cooldown_sec,
                )

            if remaining_global <= 0:
                return RateLimitStatus(
                    allowed=False,
                    reason=(
                        "Бесплатный дневной лимит для всех пользователей превышен. "
                        "Пожалуйста, введите свой API-ключ, чтобы воспользоваться чатом."
                    ),
                    remaining_global=0,
                    remaining_session=remaining_session,
                    reset_seconds=window_reset_sec,
                )

            if remaining_session <= 0:
                return RateLimitStatus(
                    allowed=False,
                    reason=(
                        f"Лимит бесплатных сообщений на сессию ({self.session_limit}) исчерпан. "
                        "Пожалуйста, введите свой API-ключ."
                    ),
                    remaining_global=remaining_global,
                    remaining_session=0,
                    reset_seconds=window_reset_sec,
                )

            # Списываем 1 глобальный запрос
            self._global_used += 1
            return RateLimitStatus(
                allowed=True,
                reason="OK",
                remaining_global=max(0, self.daily_global_limit - self._global_used),
                remaining_session=max(0, remaining_session - 1),
                reset_seconds=window_reset_sec,
            )

    def mark_upstream_exhausted(self, cooldown_seconds: Optional[int] = None) -> None:
        """
        Вызывается, если сам бесплатный провайдер (OpenRouter / Groq / Gemini)
        вернул ошибку HTTP 429 (Too Many Requests).
        Включает глобальный таймер ожидания для демо-режима.
        """
        now = time.time()
        with self._lock:
            self._refresh_window_unlocked(now)
            if cooldown_seconds is None:
                # По умолчанию ставим паузу на 1 час или до конца суточного окна
                remaining_window = max(
                    60, int(self.WINDOW_SECONDS - (now - self._window_start))
                )
                cooldown_seconds = min(3600, remaining_window)
            self._upstream_cooldown_until = max(
                self._upstream_cooldown_until, now + cooldown_seconds
            )

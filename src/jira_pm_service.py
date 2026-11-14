"""
Модуль проектного менеджера и интеграции с Jira (src/jira_pm_service.py).

Отвечает за:
1. Формирование структурированных запросов к LLM для PM-задач:
   - декомпозиция требований в иерархию Jira (Epics → Stories/Tasks → Subtasks);
   - оценка времени методом PERT (3-точечная оценка) и Story Points;
   - анализ рисков, слепых зон и уточняющих вопросов.
2. Парсинг ответа модели в типизированные объекты JiraIssue / RiskItem.
3. Экспорт результатов в Jira CSV и Markdown-отчёт.
4. (Опционально) Отправку задач в реальный проект Jira Cloud через REST API v3.

Модуль не зависит от Streamlit — всё общение с LLM идёт через LLMService,
а Jira REST API вызывается через стандартную библиотеку urllib (без лишних зависимостей).
"""

import base64
import csv
import io
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.llm_service import LLMService, ResponseTelemetry

logger = logging.getLogger(__name__)


class JiraPMError(Exception):
    """Общее исключение бизнес-логики Jira & PM Copilot."""


@dataclass
class JiraIssue:
    """
    Одна строка задачи для Jira.

    Поля соответствуют стандартным колонкам импорта CSV:
    Issue Type, Summary, Description, Acceptance Criteria, Priority,
    Original Estimate (h), Story Points + вспомогательное поле parent_summary
    для отображения иерархии.
    """

    issue_type: str
    summary: str
    description: str = ""
    acceptance_criteria: str = ""
    priority: str = "Medium"
    original_estimate_hours: Optional[float] = None
    story_points: Optional[int] = None
    parent_summary: Optional[str] = None
    pert_optimistic_hours: Optional[float] = None
    pert_realistic_hours: Optional[float] = None
    pert_pessimistic_hours: Optional[float] = None

    @property
    def computed_original_estimate_hours(self) -> Optional[float]:
        """
        Вычисляет ожидаемую оценку по формуле PERT:
        (Optimistic + 4 × Realistic + Pessimistic) / 6.
        """
        if (
            self.pert_optimistic_hours is not None
            and self.pert_realistic_hours is not None
            and self.pert_pessimistic_hours is not None
        ):
            return (
                self.pert_optimistic_hours
                + 4 * self.pert_realistic_hours
                + self.pert_pessimistic_hours
            ) / 6.0
        return self.original_estimate_hours


@dataclass
class RiskItem:
    """Строка риска из раздела Risk & Gap Analysis."""

    risk: str
    probability: str = ""
    impact: str = ""
    mitigation: str = ""
    questions: List[str] = field(default_factory=list)


@dataclass
class JiraAnalysisResult:
    """Результат комплексного PM-анализа, возвращаемый в UI."""

    issues: List[JiraIssue]
    risks: List[RiskItem]
    clarifying_questions: List[str]
    report_markdown: str
    raw_response: str
    telemetry: Optional[ResponseTelemetry] = None


class AnalysisType:
    """Константы видов PM-анализа."""

    DECOMPOSITION = "decomposition"
    ESTIMATION = "estimation"
    RISKS = "risks"

    _LABELS: Dict[str, str] = {
        DECOMPOSITION: "Декомпозиция в Jira (Epics → Stories/Tasks → Subtasks)",
        ESTIMATION: "AI-оценка времени и трудозатрат (PERT + Story Points)",
        RISKS: "Аудит рисков и слепых зон (Risk & Gap Analysis)",
    }

    @classmethod
    def label(cls, key: str) -> str:
        return cls._LABELS.get(key, key)

    @classmethod
    def all(cls) -> List[str]:
        return [cls.DECOMPOSITION, cls.ESTIMATION, cls.RISKS]


def _to_float(value: Any) -> Optional[float]:
    """Безопасное преобразование значения в float."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_int(value: Any) -> Optional[int]:
    """Безопасное преобразование значения в int."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _impact_to_priority(impact: str) -> str:
    """Сопоставляет уровень влияния риска с приоритетом Jira."""
    impact_lower = impact.lower()
    if "high" in impact_lower or "высок" in impact_lower or "критич" in impact_lower:
        return "High"
    if "low" in impact_lower or "низк" in impact_lower or "миним" in impact_lower:
        return "Low"
    return "Medium"


def _extract_json_block(text: str) -> str:
    """
    Убирает markdown-обрамление ```json ... ```, если модель его добавила.
    """
    text = text.strip()
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    # Убираем первую строку с ```json
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    # Убираем последнюю строку с ```
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_issues_from_json(data: Any) -> Tuple[List[JiraIssue], List[RiskItem], List[str]]:
    """
    Преобразует распарсенный JSON в списки JiraIssue, RiskItem и вопросов.
    """
    issues: List[JiraIssue] = []
    risks: List[RiskItem] = []
    questions: List[str] = []

    if isinstance(data, dict):
        raw_issues = data.get("issues", [])
        raw_risks = data.get("risks", [])
        questions = data.get("clarifying_questions", []) or []
    elif isinstance(data, list):
        raw_issues = data
        raw_risks = []
    else:
        return issues, risks, questions

    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        issue = JiraIssue(
            issue_type=str(item.get("issue_type", "Task")).strip() or "Task",
            summary=str(item.get("summary", "")).strip(),
            description=str(item.get("description", "")).strip(),
            acceptance_criteria=str(item.get("acceptance_criteria", "")).strip(),
            priority=str(item.get("priority", "Medium")).strip() or "Medium",
            original_estimate_hours=_to_float(item.get("original_estimate_hours")),
            story_points=_to_int(item.get("story_points")),
            parent_summary=str(item.get("parent_summary", "")).strip() or None,
            pert_optimistic_hours=_to_float(item.get("pert_optimistic_hours")),
            pert_realistic_hours=_to_float(item.get("pert_realistic_hours")),
            pert_pessimistic_hours=_to_float(item.get("pert_pessimistic_hours")),
        )
        # Если не передана итоговая оценка, но есть PERT — считаем формулой
        if (
            issue.original_estimate_hours is None
            and issue.computed_original_estimate_hours is not None
        ):
            issue.original_estimate_hours = round(
                issue.computed_original_estimate_hours, 2
            )
        issues.append(issue)

    for item in raw_risks:
        if not isinstance(item, dict):
            continue
        risk = RiskItem(
            risk=str(item.get("risk", "")).strip(),
            probability=str(item.get("probability", "")).strip(),
            impact=str(item.get("impact", "")).strip(),
            mitigation=str(item.get("mitigation", "")).strip(),
            questions=[
                str(q).strip()
                for q in item.get("questions", [])
                if str(q).strip()
            ],
        )
        if not risk.questions and item.get("question"):
            risk.questions.append(str(item.get("question")).strip())
        risks.append(risk)

        # Риски также попадают в таблицу задач для Jira CSV
        risk_issue = JiraIssue(
            issue_type="Risk",
            summary=risk.risk or "Риск",
            description=(
                f"Вероятность: {risk.probability}. Влияние: {risk.impact}."
            ),
            acceptance_criteria=risk.mitigation,
            priority=_impact_to_priority(risk.impact),
        )
        issues.append(risk_issue)

    return issues, risks, questions


def _parse_fallback_text(text: str) -> Tuple[List[JiraIssue], List[RiskItem], List[str]]:
    """
    Резервный парсер: если JSON не удалось распарсить,
    возвращаем один issue с полным текстом ответа модели.
    """
    issue = JiraIssue(
        issue_type="Task",
        summary="Результат AI-анализа",
        description=text,
    )
    return [issue], [], []


class JiraPMService:
    """
    Сервис проектного менеджмента.

    Формирует промпты для LLM, парсит структурированный ответ
    и предоставляет экспорт в CSV / Markdown.
    """

    def __init__(self, llm_service: LLMService):
        if llm_service is None:
            raise JiraPMError("LLMService не может быть None")
        self.llm_service = llm_service

    @staticmethod
    def _build_system_prompt() -> str:
        return (
            "Ты — опытный Technical Project Coordinator / Junior Project Manager. "
            "Твоя задача — проанализировать входные требования и вернуть СТРОГО JSON "
            "без markdown-обрамления (без ```json). "
            "JSON должен содержать три ключа: 'issues', 'risks', 'clarifying_questions'. "
            "\n\n"
            "Формат issues:\n"
            "[\n"
            "  {\n"
            "    \"issue_type\": \"Epic|Story|Task|Subtask|Risk\",\n"
            "    \"summary\": \"краткое название задачи\",\n"
            "    \"description\": \"подробное описание\",\n"
            "    \"acceptance_criteria\": \"критерии приёмки\",\n"
            "    \"priority\": \"Highest|High|Medium|Low|Lowest\",\n"
            "    \"original_estimate_hours\": число (или null),\n"
            "    \"story_points\": число (или null),\n"
            "    \"parent_summary\": \"название родительской задачи или null\",\n"
            "    \"pert_optimistic_hours\": число (или null),\n"
            "    \"pert_realistic_hours\": число (или null),\n"
            "    \"pert_pessimistic_hours\": число (или null)\n"
            "  }\n"
            "]\n\n"
            "Формат risks:\n"
            "[\n"
            "  {\n"
            "    \"risk\": \"описание риска\",\n"
            "    \"probability\": \"High|Medium|Low\",\n"
            "    \"impact\": \"High|Medium|Low\",\n"
            "    \"mitigation\": \"план митигации\",\n"
            "    \"questions\": [\"уточняющий вопрос 1\", \"вопрос 2\"]\n"
            "  }\n"
            "]\n\n"
            "Если виды анализа не включают оценку времени, оставляй часовые поля null. "
            "Если не включают риски — массив risks может быть пустым. "
            "Отвечай на русском языке."
        )

    def _build_user_prompt(
        self, requirements: str, analysis_types: List[str]
    ) -> str:
        type_descriptions = []
        if AnalysisType.DECOMPOSITION in analysis_types:
            type_descriptions.append(
                "- Декомпозиция: разбей требования на иерархию Epic → Story/Task → Subtask, "
                "добавь Acceptance Criteria."
            )
        if AnalysisType.ESTIMATION in analysis_types:
            type_descriptions.append(
                "- Оценка: для каждой задачи рассчитай PERT-оценку (Optimistic, Realistic, Pessimistic в часах), "
                "итоговую оценку в часах и Story Points. Объясни, от чего зависит срок, в description."
            )
        if AnalysisType.RISKS in analysis_types:
            type_descriptions.append(
                "- Риски: найди слепые зоны, противоречия, забытые зависимости. "
                "Для каждого риска укажи вероятность, влияние, митигацию и уточняющие вопросы."
            )

        analysis_block = "\n".join(type_descriptions) or "- Декомпозиция задач"

        return (
            f"Требования/описание проекта:\n---\n{requirements}\n---\n\n"
            f"Виды анализа:\n{analysis_block}\n\n"
            "Верни результат ТОЛЬКО в формате JSON с ключами 'issues', 'risks' и 'clarifying_questions'."
        )

    def _parse_response(self, text: str) -> Tuple[List[JiraIssue], List[RiskItem], List[str]]:
        """Парсит ответ модели: сначала JSON, при неудаче — fallback."""
        cleaned = _extract_json_block(text)
        try:
            data = json.loads(cleaned)
            return _parse_issues_from_json(data)
        except json.JSONDecodeError as exc:
            logger.warning("Не удалось распарсить JSON из ответа LLM: %s", exc)
            return _parse_fallback_text(text)

    def analyze(
        self, requirements: str, analysis_types: List[str]
    ) -> JiraAnalysisResult:
        """
        Запускает LLM-анализ требований и возвращает структурированный результат.

        Args:
            requirements: исходный текст требований или ТЗ.
            analysis_types: список выбранных видов анализа (AnalysisType.*).

        Returns:
            JiraAnalysisResult с задачами, рисками, вопросами, отчётом и телеметрией.
        """
        if not requirements or not requirements.strip():
            raise JiraPMError("Текст требований не может быть пустым.")

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(requirements.strip(), analysis_types)

        response, telemetry = self.llm_service.generate_response_telemetry(
            user_prompt=user_prompt,
            chat_history=[],
            system_prompt=system_prompt,
        )

        issues, risks, questions = self._parse_response(response)
        report = self._build_markdown_report(
            requirements=requirements,
            issues=issues,
            risks=risks,
            questions=questions,
            analysis_types=analysis_types,
        )

        return JiraAnalysisResult(
            issues=issues,
            risks=risks,
            clarifying_questions=questions,
            report_markdown=report,
            raw_response=response,
            telemetry=telemetry,
        )

    @staticmethod
    def export_jira_csv(issues: List[JiraIssue]) -> str:
        """
        Формирует строку CSV, совместимую с импортом Jira
        (Issues → Import Issues from CSV).
        """
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(
            [
                "Issue Type",
                "Summary",
                "Description",
                "Acceptance Criteria",
                "Priority",
                "Original Estimate",
                "Story Points",
                "Parent",
            ]
        )
        for issue in issues:
            writer.writerow(
                [
                    issue.issue_type,
                    issue.summary,
                    issue.description,
                    issue.acceptance_criteria,
                    issue.priority,
                    issue.original_estimate_hours
                    if issue.original_estimate_hours is not None
                    else "",
                    issue.story_points if issue.story_points is not None else "",
                    issue.parent_summary or "",
                ]
            )
        return output.getvalue()

    @staticmethod
    def _build_markdown_report(
        requirements: str,
        issues: List[JiraIssue],
        risks: List[RiskItem],
        questions: List[str],
        analysis_types: List[str],
    ) -> str:
        """Формирует человекочитаемый Markdown-отчёт."""
        lines: List[str] = [
            "# 📋 Отчёт Jira & PM Copilot",
            "",
            "## Входные требования",
        ]
        preview = requirements.strip()
        if len(preview) > 800:
            preview = preview[:800] + "\n\n_[Фрагмент требований обрезан для отчёта]_"
        lines.append(preview)
        lines.append("")
        lines.append("## Виды анализа")
        for at in analysis_types:
            lines.append(f"- {AnalysisType.label(at)}")
        lines.append("")

        lines.append("## Задачи для Jira")
        lines.append(
            "| Issue Type | Summary | Description | Acceptance Criteria | Priority | "
            "Original Estimate (h) | Story Points | Parent |"
        )
        lines.append(
            "|---|---|---|---|---|---|---|---|"
        )
        total_hours = 0.0
        total_points = 0
        for issue in issues:
            total_hours += issue.original_estimate_hours or 0
            total_points += issue.story_points or 0
            desc_short = (issue.description or "")[:120]
            ac_short = (issue.acceptance_criteria or "")[:120]
            lines.append(
                f"| {issue.issue_type} | {issue.summary} | {desc_short} | {ac_short} | "
                f"{issue.priority} | {issue.original_estimate_hours or ''} | "
                f"{issue.story_points or ''} | {issue.parent_summary or ''} |"
            )
        lines.append("")
        lines.append(
            f"**Итого:** оценка времени — **{total_hours:.1f} ч**, "
            f"Story Points — **{total_points}**."
        )
        lines.append("")

        if risks:
            lines.append("## 🚨 Риски и митигация")
            lines.append("| Риск | Вероятность | Влияние | Митигация |")
            lines.append("|---|---|---|---|")
            for risk in risks:
                lines.append(
                    f"| {risk.risk} | {risk.probability} | {risk.impact} | {risk.mitigation} |"
                )
            lines.append("")

        if questions:
            lines.append("## ❓ Уточняющие вопросы заказчику")
            for question in questions:
                lines.append(f"- {question}")
            lines.append("")

        return "\n".join(lines)


class JiraPushService:
    """
    Опциональная интеграция с реальным Jira Cloud через REST API v3.

    Использует только стандартную библиотек urllib, чтобы не добавлять
    лишних зависимостей в проект.
    """

    def __init__(
        self,
        domain: str,
        email: str,
        api_token: str,
        project_key: str,
    ):
        self.domain = domain.rstrip("/")
        self.email = email.strip()
        self.api_token = api_token.strip()
        self.project_key = project_key.strip().upper()

    def _request(
        self, path: str, payload: Dict[str, Any]
    ) -> Tuple[bool, Any]:
        """Отправляет POST-запрос к Jira API и возвращает (успех, тело_ответа)."""
        url = f"{self.domain}{path}"
        data = json.dumps(payload).encode("utf-8")
        credentials = base64.b64encode(
            f"{self.email}:{self.api_token}".encode()
        ).decode()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Basic {credentials}",
        }
        request = urllib.request.Request(
            url, data=data, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
                return True, body
        except urllib.error.HTTPError as exc:
            error_text = exc.read().decode("utf-8", errors="replace")
            return False, {"status": exc.code, "error": error_text}
        except Exception as exc:  # pragma: no cover
            return False, {"error": str(exc)}

    @staticmethod
    def _build_description_adf(
        description: str, acceptance_criteria: str = ""
    ) -> Dict[str, Any]:
        """Собирает Atlassian Document Format (ADF) для поля description."""
        text_parts = [description]
        if acceptance_criteria:
            text_parts.append("\n\nAcceptance Criteria:\n")
            text_parts.append(acceptance_criteria)
        full_text = "".join(text_parts)
        return {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": full_text}],
                }
            ],
        }

    def push_issues(self, issues: List[JiraIssue]) -> List[Dict[str, Any]]:
        """
        Отправляет каждую задачу в Jira как отдельный POST /rest/api/3/issue.

        Returns:
            Список результатов с полями ok, summary, body.
        """
        results: List[Dict[str, Any]] = []
        for issue in issues:
            # Jira Cloud не всегда знает произвольные типы (например, Risk),
            # поэтому риски отправляем как Task.
            issue_type = issue.issue_type
            if issue_type.lower() == "risk":
                issue_type = "Task"

            payload: Dict[str, Any] = {
                "fields": {
                    "project": {"key": self.project_key},
                    "summary": issue.summary,
                    "description": self._build_description_adf(
                        issue.description, issue.acceptance_criteria
                    ),
                    "issuetype": {"name": issue_type},
                }
            }
            if issue.priority:
                payload["fields"]["priority"] = {"name": issue.priority}

            ok, body = self._request("/rest/api/3/issue", payload)
            results.append({"ok": ok, "summary": issue.summary, "body": body})
        return results

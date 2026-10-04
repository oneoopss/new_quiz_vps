"""Схемы данных: вопрос, знание, запросы API."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    """Связь знания/вопроса с исходным фрагментом документации (§15)."""
    document: str = ""
    section: str = ""
    fragment: str = ""
    reference: str = ""
    clause: str = ""  # номер пункта правил (напр. 3.5.2.1.1), если известен


class OptionModel(BaseModel):
    text: str
    isCorrect: bool = False


class KnowledgeItem(BaseModel):
    id: Optional[int] = None
    section_id: Optional[int] = None
    section_code: str = ""
    type: Literal["rule", "constraint", "fact", "definition", "value_set", "example"] = "fact"
    statement: str
    applies_to: str = ""
    valid_values: list[str] = Field(default_factory=list)
    source_fragment: str = ""
    source_url: str = ""
    confidence: float = 1.0


class RawQuestion(BaseModel):
    """Сырой результат генерации до проверки (наружу не отдаётся)."""
    text: str = ""
    explanation: str = ""
    options: list[OptionModel] = Field(default_factory=list)
    source_fragment: str = ""
    rationale: str = ""
    thinking_type: str = ""
    knowledge_id: Optional[int] = None
    knowledge_statement: str = ""
    clause: str = ""  # номер пункта правил знания (для строки «Основание»)


class QuestionRecord(BaseModel):
    """Готовый вопрос в формате, который использует сайт-конструктор."""
    id: Optional[int] = None
    job_id: Optional[int] = None
    text: str
    explanation: str = ""
    options: list[OptionModel]
    source: SourceRef = Field(default_factory=SourceRef)
    knowledge_refs: list[int] = Field(default_factory=list)
    rationale: str = ""
    thinking_type: str = ""
    status: str = "draft"  # draft | accepted | rejected | repaired
    quality: dict[str, Any] = Field(default_factory=dict)
    generation_meta: dict[str, Any] = Field(default_factory=dict)

    def to_builder_format(self) -> dict[str, Any]:
        """Формат вопроса сайта-конструктора: {text, explanation, options:[{text, isCorrect}]}."""
        return {
            "text": self.text,
            "explanation": self.explanation,
            "options": [{"text": o.text, "isCorrect": o.isCorrect} for o in self.options],
        }


class GenerateRequest(BaseModel):
    section_code: str = ""  # одиночный выбор (обратная совместимость)
    section_codes: list[str] = Field(default_factory=list)  # мультивыбор категорий (§21)
    count: int = Field(default=10, ge=1, le=50)
    level: Literal["basic", "experienced", "expert"] = "experienced"  # уровень сложности


class JobProgress(BaseModel):
    stage: str = "queued"
    done: int = 0
    total: int = 0
    message: str = ""


class RepairRequest(BaseModel):
    feedback: str = ""
    level: Literal["basic", "experienced", "expert"] = "experienced"


class RefreshRequest(BaseModel):
    section_codes: list[str] = Field(default_factory=list)  # категории для переизвлечения знаний


class QuestionUpdate(BaseModel):
    text: Optional[str] = None
    explanation: Optional[str] = None
    options: Optional[list[OptionModel]] = None
    status: Optional[str] = None

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict

# --- SQLAlchemy ORM base & types ---
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import Text, Integer, Boolean, Date, Numeric, text as sql_text


class Base(DeclarativeBase):
    """Declarative base for ORM models.

    Если у вас уже есть свой Base в проекте, можно удалить этот класс
    и импортировать его оттуда. Здесь оставлен для самодостаточности файла.
    """


class CandidateORM(Base):
    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),  # соответствует schema.sql
    )

    date_received: Mapped[Optional[date]] = mapped_column(Date)
    last_name: Mapped[Optional[str]] = mapped_column(Text)
    first_name: Mapped[Optional[str]] = mapped_column(Text)
    middle_name: Mapped[Optional[str]] = mapped_column(Text)
    previous_last_name: Mapped[Optional[str]] = mapped_column(Text)
    sex: Mapped[Optional[str]] = mapped_column(Text)
    birth_date: Mapped[Optional[date]] = mapped_column(Date)
    birth_place: Mapped[Optional[str]] = mapped_column(Text)
    snils: Mapped[Optional[str]] = mapped_column(Text)
    passport_number: Mapped[Optional[str]] = mapped_column(Text)
    passport_issued: Mapped[Optional[str]] = mapped_column(Text)

    phone_mobile: Mapped[Optional[str]] = mapped_column(Text)
    phone_2: Mapped[Optional[str]] = mapped_column(Text)
    phone_3: Mapped[Optional[str]] = mapped_column(Text)
    email_1: Mapped[Optional[str]] = mapped_column(Text)
    email_2: Mapped[Optional[str]] = mapped_column(Text)
    email_upgo: Mapped[Optional[str]] = mapped_column(Text)

    residence_area: Mapped[Optional[str]] = mapped_column(Text)

    appointment_date: Mapped[Optional[date]] = mapped_column(Date)
    dismissal_date: Mapped[Optional[date]] = mapped_column(Date)
    confirmed_experience_years: Mapped[Optional[float]] = mapped_column(Numeric(6, 1))

    source_info: Mapped[Optional[str]] = mapped_column(Text)

    education_text: Mapped[Optional[str]] = mapped_column(Text)
    education_count: Mapped[Optional[int]] = mapped_column(Integer)
    work_text: Mapped[Optional[str]] = mapped_column(Text)
    extra_info_text: Mapped[Optional[str]] = mapped_column(Text)


# --- Pydantic schemas (JSON-friendly) ---

class CandidateOut(BaseModel):
    """Публичное представление кандидата (готово к JSON/LLM инструментам)."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    date_received: Optional[date] = None
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    previous_last_name: Optional[str] = None
    sex: Optional[str] = None
    birth_date: Optional[date] = None
    birth_place: Optional[str] = None
    snils: Optional[str] = None
    passport_number: Optional[str] = None
    passport_issued: Optional[str] = None

    phone_mobile: Optional[str] = None
    phone_2: Optional[str] = None
    phone_3: Optional[str] = None
    email_1: Optional[str] = None
    email_2: Optional[str] = None
    email_upgo: Optional[str] = None

    residence_area: Optional[str] = None

    appointment_date: Optional[date] = None
    dismissal_date: Optional[date] = None
    confirmed_experience_years: Optional[float] = None

    source_info: Optional[str] = None

    education_text: Optional[str] = None
    education_count: Optional[int] = None
    work_text: Optional[str] = None
    extra_info_text: Optional[str] = None


 # Для совместимости с прежним импортом: Candidate == CandidateOut
Candidate = CandidateOut


__all__ = [
    "Base",
    "CandidateORM",
    "CandidateOut",
    "Candidate",
]

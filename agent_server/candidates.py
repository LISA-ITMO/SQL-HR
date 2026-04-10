from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Boolean, Date, Integer, Numeric, Text


class Base(DeclarativeBase):
    pass


class CandidateORM(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(Text, primary_key=True)

    # Демография
    sex:        Mapped[Optional[str]]  = mapped_column(Text)
    age:        Mapped[Optional[int]]  = mapped_column(Integer)
    birth_date: Mapped[Optional[date]] = mapped_column(Date)

    # Профессиональный профиль
    desired_position: Mapped[Optional[str]]   = mapped_column(Text)
    experience_years: Mapped[Optional[float]] = mapped_column(Numeric(6, 2))
    last_employer:    Mapped[Optional[str]]   = mapped_column(Text)
    last_position:    Mapped[Optional[str]]   = mapped_column(Text)
    work_text:        Mapped[Optional[str]]   = mapped_column(Text)

    # Образование
    education_text: Mapped[Optional[str]] = mapped_column(Text)

    # Условия работы
    salary:          Mapped[Optional[int]]  = mapped_column(Integer)
    employment_type: Mapped[Optional[str]]  = mapped_column(Text)
    schedule:        Mapped[Optional[str]]  = mapped_column(Text)
    relocation:      Mapped[Optional[bool]] = mapped_column(Boolean)
    business_trips:  Mapped[Optional[bool]] = mapped_column(Boolean)

    # Местоположение
    city: Mapped[Optional[str]] = mapped_column(Text)

    # Дополнительно
    has_car: Mapped[Optional[bool]] = mapped_column(Boolean)


class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str

    # Демография
    sex:        Optional[str]  = None
    age:        Optional[int]  = None
    birth_date: Optional[date] = None

    # Профессиональный профиль
    desired_position: Optional[str]   = None
    experience_years: Optional[float] = None
    last_employer:    Optional[str]   = None
    last_position:    Optional[str]   = None
    work_text:        Optional[str]   = None

    # Образование
    education_text: Optional[str] = None

    # Условия работы
    salary:          Optional[int]  = None
    employment_type: Optional[str]  = None
    schedule:        Optional[str]  = None
    relocation:      Optional[bool] = None
    business_trips:  Optional[bool] = None

    # Местоположение
    city: Optional[str] = None

    # Дополнительно
    has_car: Optional[bool] = None


Candidate = CandidateOut

__all__ = ["Base", "CandidateORM", "CandidateOut", "Candidate"]

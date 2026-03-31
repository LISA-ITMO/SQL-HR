"""
Модуль для переранжирования кандидатов через CrossEncoder.

Использует sentence-transformers для вычисления релевантности
кандидатов относительно текстового запроса пользователя.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from huggingface_hub import snapshot_download
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)


class CandidateReranker:
    """Синглтон для переранжирования кандидатов через CrossEncoder."""

    _instance: Optional[CandidateReranker] = None
    _model: Optional[CrossEncoder] = None
    _model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    _cache_dir: Optional[str] = None
    _max_length: int = 512
    _enabled: bool = True
    _required_files: Tuple[str, ...] = (
        "config.json",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "vocab.txt",
        "sentencepiece.bpe.model",
        "spiece.model",
    )

    def __new__(cls) -> CandidateReranker:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._model is not None:
            return

        # Загружаем конфигурацию из переменных окружения
        self._enabled = os.getenv("ENABLE_RERANKING", "True").lower() == "true"
        self._model_name = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        self._cache_dir = os.getenv("CROSS_ENCODER_CACHE_DIR", "/models/cross-encoder")
        self._max_length = int(os.getenv("RERANKER_MAX_LENGTH", "512"))

        if not self._enabled:
            logger.info("reranker disabled (ENABLE_RERANKING=False)")
            return

        logger.info(
            "reranker init model=%s max_length=%s cache_dir=%s",
            self._model_name,
            self._max_length,
            self._cache_dir,
        )
        try:
            start_time = time.perf_counter()
            model_path = self._ensure_local_model_dir()
            self._model = CrossEncoder(
                model_path,
                max_length=self._max_length,
                local_files_only=True,
            )
            elapsed = time.perf_counter() - start_time
            logger.info("reranker loaded in %.2f sec", elapsed)
        except Exception:
            logger.exception("reranker failed to load model")
            self._enabled = False

    def _ensure_local_model_dir(self) -> str:
        """Downloads only required model files into a plain local directory."""
        if not self._cache_dir:
            raise ValueError("CROSS_ENCODER_CACHE_DIR is not set")

        model_dir = Path(self._cache_dir)
        model_dir.mkdir(parents=True, exist_ok=True)

        has_weights = any((model_dir / name).exists() for name in ("model.safetensors", "pytorch_model.bin"))
        has_config = (model_dir / "config.json").exists()
        has_tokenizer = any(
            (model_dir / name).exists()
            for name in ("tokenizer.json", "vocab.txt", "spiece.model", "sentencepiece.bpe.model")
        )

        if not (has_weights and has_config and has_tokenizer):
            logger.info("reranker downloading required files into %s", model_dir)
            snapshot_download(
                repo_id=self._model_name,
                local_dir=str(model_dir),
                allow_patterns=list(self._required_files),
            )
            self._cleanup_local_model_dir(model_dir)

        return str(model_dir)

    def _cleanup_local_model_dir(self, model_dir: Path) -> None:
        cache_dir = model_dir / ".cache"
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)

        duplicate_bin = model_dir / "pytorch_model.bin"
        if duplicate_bin.exists() and (model_dir / "model.safetensors").exists():
            duplicate_bin.unlink(missing_ok=True)

    def _build_candidate_text(self, candidate: Dict[str, Any]) -> str:
        """Строит текстовое представление кандидата для переранжирования.

        Args:
            candidate: Словарь с данными кандидата (из БД)

        Returns:
            Текстовая строка, объединяющая ключевые поля кандидата
        """
        parts: List[str] = []

        # ФИО
        name_parts = [
            candidate.get("last_name"),
            candidate.get("first_name"),
            candidate.get("middle_name"),
        ]
        full_name = " ".join([p for p in name_parts if p])
        if full_name:
            parts.append(full_name)

        # Место жительства
        residence = candidate.get("residence_area")
        if residence:
            parts.append(f"Место жительства: {residence}")

        # Образование
        education = candidate.get("education_text")
        if education:
            parts.append(f"Образование: {education}")

        # Опыт работы
        work = candidate.get("work_text")
        if work:
            parts.append(f"Опыт работы: {work}")

        # Дополнительная информация
        extra = candidate.get("extra_info_text")
        if extra:
            parts.append(f"Дополнительно: {extra}")

        # Количество образований
        edu_count = candidate.get("education_count")
        if edu_count is not None:
            parts.append(f"Количество образований: {edu_count}")

        # Подтвержденный опыт в годах
        exp_years = candidate.get("confirmed_experience_years")
        if exp_years is not None:
            parts.append(f"Опыт работы (последняя должность): {exp_years} лет")

        return " | ".join(parts)

    def rerank_candidates(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Переранжирует список кандидатов относительно текстового запроса.

        Args:
            query: Текстовый запрос пользователя
            candidates: Список словарей с данными кандидатов (из БД)
            top_k: Количество кандидатов для возврата (по умолчанию 5)

        Returns:
            Список кандидатов, отсортированный по релевантности (топ-K)
        """
        if not self._enabled or self._model is None:
            logger.info("reranker disabled or not loaded; returning candidates as-is")
            return candidates[:top_k]

        if not candidates:
            return []

        if not query or not query.strip():
            logger.warning("reranker: empty query; returning candidates as-is")
            return candidates[:top_k]

        try:
            start_time = time.perf_counter()

            # Строим текстовые представления кандидатов
            candidate_texts = [self._build_candidate_text(c) for c in candidates]

            # Формируем пары (запрос, текст кандидата)
            pairs = [(query, text) for text in candidate_texts]

            # Вычисляем оценки релевантности
            scores = self._model.predict(pairs)

            # Объединяем кандидатов с их оценками и сортируем по убыванию
            ranked = sorted(
                zip(candidates, scores),
                key=lambda x: x[1],
                reverse=True,
            )

            # Возвращаем топ-K кандидатов
            result = [candidate for candidate, score in ranked[:top_k]]

            elapsed = time.perf_counter() - start_time
            logger.info(
                "reranker done input=%s output=%s elapsed=%.3f sec",
                len(candidates),
                len(result),
                elapsed,
            )

            return result

        except Exception:
            logger.exception("reranker failed; returning candidates as-is")
            return candidates[:top_k]

    def rerank_with_scores(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Переранжирует кандидатов и возвращает с оценками релевантности.

        Args:
            query: Текстовый запрос пользователя
            candidates: Список словарей с данными кандидатов (из БД)
            top_k: Количество кандидатов для возврата (None = все)

        Returns:
            Список кортежей [(кандидат, score)], отсортированный по убыванию
        """
        if not self._enabled or self._model is None:
            logger.info("reranker disabled or not loaded; returning candidates with dummy scores")
            result = [(c, 0.0) for c in candidates]
            return result if top_k is None else result[:top_k]

        if not candidates:
            return []

        if not query or not query.strip():
            logger.warning("reranker: empty query; returning candidates with dummy scores")
            result = [(c, 0.0) for c in candidates]
            return result if top_k is None else result[:top_k]

        try:
            start_time = time.perf_counter()

            # Строим текстовые представления кандидатов
            candidate_texts = [self._build_candidate_text(c) for c in candidates]

            # Формируем пары (запрос, текст кандидата)
            pairs = [(query, text) for text in candidate_texts]

            # Вычисляем оценки релевантности
            scores = self._model.predict(pairs)

            # Объединяем и сортируем по убыванию
            ranked = sorted(
                zip(candidates, scores),
                key=lambda x: x[1],
                reverse=True,
            )

            result = ranked if top_k is None else ranked[:top_k]

            elapsed = time.perf_counter() - start_time
            logger.info(
                "reranker_with_scores done input=%s output=%s elapsed=%.3f sec",
                len(candidates),
                len(result),
                elapsed,
            )

            return result

        except Exception:
            logger.exception("reranker failed; returning candidates with dummy scores")
            result = [(c, 0.0) for c in candidates]
            return result if top_k is None else result[:top_k]


# Глобальный экземпляр реранкера (синглтон)
_reranker_instance: Optional[CandidateReranker] = None


def get_reranker() -> CandidateReranker:
    """Возвращает глобальный экземпляр реранкера (ленивая инициализация)."""
    global _reranker_instance
    if _reranker_instance is None:
        _reranker_instance = CandidateReranker()
    return _reranker_instance


def rerank_candidates(
    query: str,
    candidates: List[Dict[str, Any]],
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Переранжирует список кандидатов относительно текстового запроса.

    Удобная функция-обертка над CandidateReranker.rerank_candidates.

    Args:
        query: Текстовый запрос пользователя
        candidates: Список словарей с данными кандидатов (из БД)
        top_k: Количество кандидатов для возврата (по умолчанию 5)

    Returns:
        Список кандидатов, отсортированный по релевантности (топ-K)
    """
    reranker = get_reranker()
    return reranker.rerank_candidates(query, candidates, top_k)


def rerank_with_scores(
    query: str,
    candidates: List[Dict[str, Any]],
    top_k: Optional[int] = None,
) -> List[Tuple[Dict[str, Any], float]]:
    """Переранжирует кандидатов и возвращает с оценками релевантности.

    Удобная функция-обертка над CandidateReranker.rerank_with_scores.

    Args:
        query: Текстовый запрос пользователя
        candidates: Список словарей с данными кандидатов (из БД)
        top_k: Количество кандидатов для возврата (None = все)

    Returns:
        Список кортежей [(кандидат, score)], отсортированный по убыванию
    """
    reranker = get_reranker()
    return reranker.rerank_with_scores(query, candidates, top_k)

from __future__ import annotations

import ast
import json
import logging
import os
import uuid
import time
import functools
from datetime import date, datetime
from contextvars import ContextVar
from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict, Union
from uuid import UUID

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import and_, create_engine, func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

# Optional advanced LangGraph tool features (state/tool_call_id injection + Command updates).
try:
    from langgraph.prebuilt import InjectedState  # type: ignore
except Exception:  # pragma: no cover
    InjectedState = object  # type: ignore

try:
    from langchain_core.tools import InjectedToolCallId  # type: ignore
except Exception:  # pragma: no cover
    InjectedToolCallId = object  # type: ignore

try:
    from langgraph.types import Command  # type: ignore
except Exception:  # pragma: no cover
    Command = None  # type: ignore
from langchain_openai import ChatOpenAI

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from candidates import CandidateORM as C
from candidates import CandidateOut
from prompts import (
    MAIN_AGENT_SYSTEM_PROMPT,
    CLARIFY_WITH_MAIN_SYSTEM_PROMPT,
    SUB_AGENT_LAST_TRY_PROMPT,
    SUB_AGENT_SYSTEM_PROMPT,
)

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)

CURRENT_SESSION_ID: ContextVar[Optional[str]] = ContextVar("CURRENT_SESSION_ID", default=None)

REPORT_DIR = os.getenv("REPORT_DIR", "result")
SUB_AGENT_REPORT_FILE = os.getenv(
    "SUB_AGENT_REPORT_FILE",
    os.path.join(REPORT_DIR, "sup_agent_report.txt"),
)
SAVE_LOGS = os.getenv("SAVE_LOGS", "True").lower() == "true"
SPEED_REPORT_PREFIX = "speed"

CURRENT_SPEED_REPORT: ContextVar[Optional[str]] = ContextVar("CURRENT_SPEED_REPORT", default=None)

def _write_sub_agent_report(report: str, messages: List[AnyMessage], task: str) -> None:
    """Persist sub-agent tool calls/results and final report to a local file."""
    if not SAVE_LOGS:
        logger.info("sub-agent report skipped (SAVE_LOGS=False)")
        return
    try:
        os.makedirs(os.path.dirname(SUB_AGENT_REPORT_FILE) or ".", exist_ok=True)
        base, ext = os.path.splitext(SUB_AGENT_REPORT_FILE)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = f"{base}_{timestamp}{ext or '.txt'}"
        lines: List[str] = []
        lines.append("task:")
        lines.append(task or "")
        lines.append("")
        lines.append("tool_calls:")
        for msg in messages:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for call in msg.tool_calls:
                    name = call.get("name") if isinstance(call, dict) else None
                    args = call.get("args") if isinstance(call, dict) else None
                    lines.append(f"- call name={name} args={args}")
            elif isinstance(msg, ToolMessage):
                tool_name = _tool_name(msg)
                content = msg.content
                lines.append(f"- result name={tool_name} content={content}")
        lines.append("")
        lines.append("report:")
        lines.append(report or "")
        lines.append("")
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
    except Exception:
        logger.exception("failed to write sub-agent report")


def _init_speed_report(session_id: Optional[str]) -> Optional[str]:
    if not SAVE_LOGS:
        return None
    try:
        if session_id and session_id in SESSIONS:
            SESSIONS[session_id]["speed_report_path"] = None
        os.makedirs(REPORT_DIR or ".", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{SPEED_REPORT_PREFIX}_{timestamp}.txt"
        report_path = os.path.join(REPORT_DIR or ".", filename)
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write("")
        if session_id and session_id in SESSIONS:
            SESSIONS[session_id]["speed_report_path"] = report_path
        CURRENT_SPEED_REPORT.set(report_path)
        return report_path
    except Exception:
        logger.exception("failed to initialize speed report")
        return None


def _append_speed_report(session_id: Optional[str], node_name: str, duration_sec: float) -> None:
    if not SAVE_LOGS:
        return
    report_path = None
    if session_id and session_id in SESSIONS:
        report_path = SESSIONS[session_id].get("speed_report_path")
    if not report_path:
        report_path = CURRENT_SPEED_REPORT.get()
    if not report_path:
        return
    try:
        with open(report_path, "a", encoding="utf-8") as handle:
            handle.write(f"{node_name}-{duration_sec:.6f}\n")
    except Exception:
        logger.exception("failed to append speed report")


def timed_node(node_name: str):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration = time.perf_counter() - start
                session_id = None
                state = args[0] if args else None
                if isinstance(state, dict):
                    session_id = state.get("session_id")
                _append_speed_report(session_id, node_name, duration)
        return wrapper
    return decorator


def _parse_tool_payload(content: Any) -> Any:
    """Best-effort parser for tool outputs coming through ToolMessage.content."""
    if isinstance(content, (dict, list)):
        return content
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except Exception:
        try:
            return ast.literal_eval(content)
        except Exception:
            return content


def _tool_name(msg: AnyMessage) -> str:
    """Extract tool name from ToolMessage in a version-tolerant way."""
    name = getattr(msg, "name", None)
    if isinstance(name, str) and name:
        return name
    kw = getattr(msg, "additional_kwargs", None) or {}
    if isinstance(kw, dict) and isinstance(kw.get("name"), str):
        return kw["name"]
    return ""


def _should_compact_tool_messages(messages: List[AnyMessage]) -> bool:
    for msg in messages:
        if isinstance(msg, ToolMessage) and _tool_name(msg) == "save_candidate_ids":
            return True
    return False


def _compact_candidate_refs(items: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return out
    for item in items:
        cid = None
        if isinstance(item, dict):
            cid = item.get("id")
        elif isinstance(item, str):
            cid = item
        if cid:
            out.append({"id": str(cid), "saved_in_db": True})
    return out


def _extract_saved_info(messages: List[AnyMessage]) -> Dict[str, Dict[str, Any]]:
    saved: Dict[str, Dict[str, Any]] = {}
    for msg in messages:
        if not isinstance(msg, ToolMessage) or _tool_name(msg) != "save_candidate_ids":
            continue
        payload = _parse_tool_payload(msg.content)
        if not isinstance(payload, dict):
            continue
        for item in payload.get("saved") or []:
            cid = None
            info: Dict[str, Any] = {}
            if isinstance(item, dict):
                cid = item.get("id")
                if item.get("full_name"):
                    info["full_name"] = item.get("full_name")
                if item.get("summary"):
                    info["summary"] = item.get("summary")
            else:
                cid = item
            if cid:
                info["id"] = str(cid)
                saved[str(cid)] = info
    return saved


def _compact_tool_payload(
    payload: Any, saved_info: Dict[str, Dict[str, Any]], tool_name: str
) -> tuple[Any, bool]:
    if not isinstance(payload, dict):
        return payload, False
    changed = False
    updated = dict(payload)
    if tool_name == "db_search" and isinstance(payload.get("candidates"), list):
        candidates = []
        for item in payload.get("candidates") or []:
            if isinstance(item, dict):
                cid = item.get("id")
                if cid and str(cid) in saved_info:
                    candidates.append({"id": str(cid), "saved_in_db": True})
                    changed = True
                    continue
            candidates.append(item)
        updated["candidates"] = candidates
    return updated, changed


def _compact_tool_messages_in_place(messages: List[AnyMessage]) -> None:
    saved_info = _extract_saved_info(messages)
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        tool_name = _tool_name(msg)
        payload = _parse_tool_payload(msg.content)
        compacted, changed = _compact_tool_payload(payload, saved_info, tool_name)
        if changed:
            msg.content = json.dumps(compacted, ensure_ascii=False, default=str)


def _candidate_full_name(candidate: Dict[str, Any]) -> str:
    parts = [candidate.get("last_name"), candidate.get("first_name"), candidate.get("middle_name")]
    return " ".join([p for p in parts if p])


def _is_compact_candidate(candidate: Any) -> bool:
    if not isinstance(candidate, dict):
        return False
    allowed = {"id", "full_name", "summary", "saved_in_db"}
    keys = set(candidate.keys())
    return bool(keys) and keys.issubset(allowed)


def _are_compact_candidates(candidates: Any) -> bool:
    if not isinstance(candidates, list) or not candidates:
        return False
    return all(_is_compact_candidate(item) for item in candidates if isinstance(item, dict))


# ------------------------
# Infrastructure (DB + LLM)
# ------------------------

DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "postgres")
DB_HOST = os.getenv("POSTGRES_HOST", "postgres")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "candidates_db")

engine = create_engine(
    f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class API:
    llm: ChatOpenAI

    def __init__(self) -> None:
        use_llama = os.getenv("USE_LLAMA", "True") == "True"

        llama_model = os.getenv("LLAMA_MODEL")
        llama_key = os.getenv("LLAMA_KEY")
        llama_base_url = os.getenv("LLAMA_BASE_URL", "http://vllm:8001/v1")

        proxy_model = os.getenv("PROXY_MODEL")
        proxy_api_key = os.getenv("PROXY_API_KEY")
        proxy_base_url = os.getenv("PROXY_BASE_URL", "https://api.openai.com/v1")

        llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1024"))

        logger.info(
            "LLM init: use_llama=%s, llama_model=%r, llama_base_url=%r, proxy_model=%r, proxy_base_url=%r, proxy_key_set=%s, llm_max_tokens=%s",
            use_llama,
            llama_model,
            llama_base_url,
            proxy_model,
            proxy_base_url,
            bool(proxy_api_key),
            llm_max_tokens,
        )

        if use_llama:
            if not llama_model:
                raise RuntimeError("USE_LLAMA=true, но LLAMA_MODEL не задан")
            self.llm = ChatOpenAI(
                model=llama_model,
                api_key=llama_key,
                base_url=llama_base_url,
                temperature=0,
                max_tokens=llm_max_tokens,
            )
        else:
            if not proxy_model:
                raise RuntimeError("USE_LLAMA=false, но PROXY_MODEL не задан")
            self.llm = ChatOpenAI(
                model=proxy_model,
                api_key=proxy_api_key,
                base_url=proxy_base_url,
                temperature=0,
                max_tokens=llm_max_tokens,
            )


api = API()
llm = api.llm


# ------------------------
# Models
# ------------------------


class QuerySpec(BaseModel):
    birth_date_from: Optional[date] = Field(
        default=None,
        description="Дата рождения от (YYYY-MM-DD).",
    )
    birth_date_to: Optional[date] = Field(
        default=None,
        description="Дата рождения до (YYYY-MM-DD).",
    )
    appointment_date_from: Optional[date] = Field(
        default=None,
        description="Дата назначения от (YYYY-MM-DD).",
    )
    appointment_date_to: Optional[date] = Field(
        default=None,
        description="Дата назначения до (YYYY-MM-DD).",
    )
    dismissal_date_from: Optional[date] = Field(
        default=None,
        description="Дата увольнения от (YYYY-MM-DD).",
    )
    dismissal_date_to: Optional[date] = Field(
        default=None,
        description="Дата увольнения до (YYYY-MM-DD).",
    )
    keywords_any: List[str] = Field(
        default_factory=list,
        description="Список ключевых слов, из которых должно встретиться хотя бы одно в текстовых полях.",
    )
    keywords_all: List[str] = Field(
        default_factory=list,
        description="Ключевые слова, которые обязательно должны присутствовать одновременно в текстовых полях.",
    )
    keywords_not: List[str] = Field(
        default_factory=list,
        description="Ключевые слова, которые не должны встречаться в текстовых полях.",
    )
    education_count: Optional[int] = Field(
        default=None,
        ge=0,
        description="Минимальное количество образований (>=).",
    )
    confirmed_experience_years_min: Optional[float] = Field(
        default=None,
        ge=0,
        description="Минимальный подтвержденный опыт на последней работе в годах (>=).",
    )
    offset: int = Field(
        0,
        ge=0,
        description=(
            "Сколько строк пропустить (pagination). "
            "Назначай только если предыдущий такой же запрос вернул максимум (limit)."
        ),
    )
    limit: int = Field(
        5,
        ge=1,
        le=5,
        description="Сколько строк вернуть в рамках одного запроса к БД.",
    )


def _short(txt: Optional[str], limit: int = 1000) -> Optional[str]:
    if not txt:
        return txt
    return txt if len(txt) <= limit else (txt[:limit] + "…")


def _compact_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("education_text", "work_text", "extra_info_text"):
        if key in candidate:
            candidate[key] = _short(candidate.get(key))
    for key in ("date_received", "birth_date", "appointment_date", "dismissal_date"):
        value = candidate.get(key)
        if hasattr(value, "isoformat"):
            candidate[key] = value.isoformat()
    if "confirmed_experience_years" in candidate and candidate["confirmed_experience_years"] is not None:
        candidate["confirmed_experience_years"] = float(candidate["confirmed_experience_years"])
    return candidate


def get_from_query(spec: QuerySpec, session: Session) -> List[CandidateOut]:
    def _clean_keywords(values: Optional[List[str]]) -> List[str]:
        cleaned: List[str] = []
        for raw in values or []:
            if raw is None:
                continue
            value = str(raw).strip()
            if value:
                cleaned.append(value)
        return cleaned

    keywords_all = _clean_keywords(spec.keywords_all)
    keywords_any = _clean_keywords(spec.keywords_any)
    keywords_not = _clean_keywords(spec.keywords_not)

    clauses = []
    if spec.birth_date_from:
        clauses.append(C.birth_date >= spec.birth_date_from)
    if spec.birth_date_to:
        clauses.append(C.birth_date <= spec.birth_date_to)
    if spec.appointment_date_from:
        clauses.append(C.appointment_date >= spec.appointment_date_from)
    if spec.appointment_date_to:
        clauses.append(C.appointment_date <= spec.appointment_date_to)
    if spec.dismissal_date_from:
        clauses.append(C.dismissal_date >= spec.dismissal_date_from)
    if spec.dismissal_date_to:
        clauses.append(C.dismissal_date <= spec.dismissal_date_to)
    if spec.education_count is not None:
        clauses.append(C.education_count >= spec.education_count)
    if spec.confirmed_experience_years_min is not None:
        clauses.append(C.confirmed_experience_years >= spec.confirmed_experience_years_min)

    def _text_match(keyword: str):
        pattern = f"%{keyword}%"
        # NULL-safe matching so NOT conditions don't null out the whole filter.
        return or_(
            func.coalesce(C.last_name, "").ilike(pattern),
            func.coalesce(C.first_name, "").ilike(pattern),
            func.coalesce(C.middle_name, "").ilike(pattern),
            func.coalesce(C.residence_area, "").ilike(pattern),
            func.coalesce(C.education_text, "").ilike(pattern),
            func.coalesce(C.work_text, "").ilike(pattern),
            func.coalesce(C.extra_info_text, "").ilike(pattern),
        )

    for kw in keywords_all:
        clauses.append(_text_match(kw))

    any_clauses = [_text_match(kw) for kw in keywords_any]
    if any_clauses:
        clauses.append(or_(*any_clauses))

    not_clauses = [~_text_match(kw) for kw in keywords_not]
    if not_clauses:
        clauses.append(and_(*not_clauses))

    stmt = select(C)
    if clauses:
        stmt = stmt.where(and_(*clauses))
    if int(spec.offset or 0) > 0:
        stmt = stmt.offset(int(spec.offset))
    stmt = stmt.limit(min(int(spec.limit or 5), 5))

    rows = session.scalars(stmt).all()
    return [CandidateOut.model_validate(r) for r in rows]


def fetch_candidates_by_ids(ids: List[str]) -> List[Dict[str, Any]]:
    if not ids:
        return []
    uniq: List[str] = []
    seen: set[str] = set()
    for cid in ids:
        s = str(cid)
        if s not in seen:
            uniq.append(s)
            seen.add(s)
    uuid_ids: List[uuid.UUID] = []
    for s in uniq:
        try:
            uuid_ids.append(uuid.UUID(s))
        except Exception:
            continue

    if not uuid_ids:
        return []

    with SessionLocal() as session:
        stmt = select(C).where(C.id.in_(uuid_ids))
        rows = session.scalars(stmt).all()
        output: List[Dict[str, Any]] = []
        for row in rows:
            data = CandidateOut.model_validate(row).model_dump()
            output.append(_compact_candidate(data))
        return output


# ------------------------
# LangGraph state + reducers
# ------------------------


def add_messages(left: List[AnyMessage], right: List[AnyMessage]) -> List[AnyMessage]:
    out = left + right
    if _should_compact_tool_messages(out):
        _compact_tool_messages_in_place(out)
    return out


def add_unique_ids(left: List[str], right: List[str]) -> List[str]:
    out: List[str] = list(left)
    seen = set(out)
    for x in right:
        s = str(x)
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


def add_unique_candidates(
    left: List[Dict[str, Any]], right: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = list(left)
    index_by_id: Dict[str, int] = {}
    for idx, item in enumerate(out):
        cid = item.get("id") if isinstance(item, dict) else None
        if cid:
            index_by_id[str(cid)] = idx
    for item in right:
        if not isinstance(item, dict):
            continue
        cid = item.get("id")
        if cid:
            key = str(cid)
            if key in index_by_id:
                out[index_by_id[key]] = item
                continue
            index_by_id[key] = len(out)
        out.append(item)
    return out


class MainState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    session_id: str


class SubState(TypedDict, total=False):
    task: str
    context: List[AnyMessage]
    iterations_left: int
    messages: Annotated[List[AnyMessage], add_messages]
    last_pool: List[str]
    report: str
    candidates: Annotated[List[Dict[str, Any]], add_unique_candidates]
    need_user: bool
    user_question: str
    session_id: str
    cancelled: bool


# ------------------------
# Sub-agent tools (exactly 3)
# ------------------------


class SavedCandidateSummary(BaseModel):
    id: str
    full_name: Optional[str] = None
    summary: Optional[str] = None


@tool
def clarify_with_main(
    question: str,
    state: Annotated[dict, InjectedState],
) -> Dict[str, Any]:
    """Назначение:
        Задать уточняющий вопрос основному агенту, если данных не хватает.

        Когда использовать:
        - критерии поиска неясны (позиция, опыт, локация, зарплата, навыки и т.д.)
        - пользователь просит “лучших”, но не говорит по каким параметрам

        Вход:
        - question: что именно нужно уточнить

        Выход:
        - текст уточняющего вопроса
    """

    logger.info("tool=clarify_with_main start question=%r", _short(question))
    context_msgs = state.get("context")
    if not isinstance(context_msgs, list):
        context_msgs = []

    # Build a valid tool-message pair for providers that require tool_call_id matching.
    call_id = f"clarify_{uuid.uuid4().hex}"
    tool_question = f"тул спрашивает уточняющий вопрос: {question}".strip()

    msgs: List[AnyMessage] = [
        SystemMessage(content=CLARIFY_WITH_MAIN_SYSTEM_PROMPT),
        *context_msgs,
        ToolMessage(content=tool_question, tool_call_id=call_id),
    ]
    try:
        raw = llm.invoke(msgs).content
        result = {"answer": str(raw)}
        logger.info("tool=clarify_with_main done answer_len=%s", len(result["answer"] or ""))
        return result
    except Exception:
        logger.exception("clarify_with_main failed")
        return {"answer": "Не удалось уточнить детали автоматически."}


@tool
def db_search(
    spec: QuerySpec,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Any:
    """Поиск кандидатов по QuerySpec, возвращает список и count."""
    logger.info(
        "tool=db_search start keywords_any=%s keywords_all=%s keywords_not=%s limit=%s",
        len(spec.keywords_any or []),
        len(spec.keywords_all or []),
        len(spec.keywords_not or []),
        spec.limit,
    )
    with SessionLocal() as session:
        rows = get_from_query(spec, session=session)

    allowed_fields: set[str] = set()
    if spec.birth_date_from or spec.birth_date_to:
        allowed_fields.add("birth_date")
    if spec.appointment_date_from or spec.appointment_date_to:
        allowed_fields.add("appointment_date")
    if spec.dismissal_date_from or spec.dismissal_date_to:
        allowed_fields.add("dismissal_date")
    if spec.education_count is not None:
        allowed_fields.add("education_count")
    if spec.confirmed_experience_years_min is not None:
        allowed_fields.add("confirmed_experience_years")
    if (spec.keywords_any or spec.keywords_all or spec.keywords_not):
        allowed_fields.update(
            {
                "last_name",
                "first_name",
                "middle_name",
                "residence_area",
                "education_text",
                "work_text",
                "extra_info_text",
            }
        )

    payload: List[Dict[str, Any]] = []
    for c in rows:
        record = {
            "id": str(c.id),
            "last_name": c.last_name,
            "first_name": c.first_name,
            "middle_name": c.middle_name,
            "residence_area": c.residence_area,
            "birth_date": c.birth_date.isoformat() if c.birth_date else None,
            "education_count": c.education_count,
            "education_text": _short(c.education_text),
            "work_text": _short(c.work_text),
            "extra_info_text": _short(c.extra_info_text),
            "appointment_date": c.appointment_date.isoformat() if c.appointment_date else None,
            "dismissal_date": c.dismissal_date.isoformat() if c.dismissal_date else None,
            "confirmed_experience_years": float(c.confirmed_experience_years)
            if c.confirmed_experience_years is not None
            else None,
        }
        filtered = {"id": record["id"]}
        for key in allowed_fields:
            if key in record:
                filtered[key] = record[key]
        payload.append(filtered)
    result = {"count": len(payload), "candidates": payload}
    logger.info("tool=db_search done count=%s", result["count"])

    # If Command is available, update state directly (no extra collector/finalize nodes).
    if Command is not None:
        last_pool = [str(x.get("id")) for x in payload if isinstance(x, dict) and x.get("id")]
        return Command(
            update={
                "last_pool": last_pool,
                "messages": [
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=tool_call_id,
                        name="db_search",
                    )
                ],
            }
        )

    return result


@tool
def save_candidate_ids(
    candidates: List[SavedCandidateSummary],
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Any:
    """Сохранить выбранные ID кандидатов (с кратким описанием, если доступно)."""
    logger.info("tool=save_candidate_ids start ids_count=%s", len(candidates or []))
    normalized: List[str] = []
    seen: set[str] = set()
    saved_info: Dict[str, Dict[str, Any]] = {}
    for item in candidates or []:
        cid = str(item.id)
        saved_entry: Dict[str, Any] = {"id": cid}
        if item.full_name:
            saved_entry["full_name"] = item.full_name
        if item.summary:
            saved_entry["summary"] = item.summary
        saved_info[cid] = saved_entry
        if cid not in seen:
            normalized.append(cid)
            seen.add(cid)
    saved_payload = [saved_info[cid] for cid in normalized]
    result = {"saved": saved_payload, "saved_count": len(saved_payload)}
    logger.info("tool=save_candidate_ids done saved_count=%s", result["saved_count"])

    session_id = state.get("session_id") or CURRENT_SESSION_ID.get()
    if session_id and session_id in SESSIONS:
        existing = SESSIONS[session_id].get("pending_candidate_ids") or []
        merged: List[str] = []
        seen_pending: set[str] = set()
        for cid in list(existing) + normalized:
            s = str(cid)
            if s not in seen_pending:
                merged.append(s)
                seen_pending.add(s)
        SESSIONS[session_id]["pending_candidate_ids"] = merged
        SESSIONS[session_id]["pending_candidates"] = []
        logger.info(
            "tool=save_candidate_ids pending_update session_id=%s candidates=%s",
            session_id,
            len(merged),
        )
    else:
        logger.info("tool=save_candidate_ids pending_update skipped session_id=%r", session_id)

    if Command is not None:
        selected_candidates = fetch_candidates_by_ids(normalized) if normalized else []
        return Command(
            update={
                "candidates": selected_candidates,
                "messages": [
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=tool_call_id,
                        name="save_candidate_ids",
                    )
                ],
            }
        )

    return result


sub_tools = [db_search, save_candidate_ids]
sub_tool_node = ToolNode(sub_tools)


@timed_node("sub.tools")
def sub_tools_node(state: SubState) -> SubState:
    return sub_tool_node.invoke(state)


# ------------------------
# Sub-agent nodes
# ------------------------


@timed_node("sub.agent")
def sub_agent_node(state: SubState) -> SubState:
    logger.info(
        "node=sub_agent_node start iterations_left=%s messages=%s",
        state.get("iterations_left"),
        len(state.get("messages", []) or []),
    )
    session_id = state.get("session_id")
    if _is_cancel_requested(session_id):
        session_data = SESSIONS.get(session_id) if session_id else None
        pending_ids = list((session_data or {}).get("pending_candidate_ids") or [])
        pending_candidates = fetch_candidates_by_ids(pending_ids) if pending_ids else []
        logger.info(
            "node=sub_agent_node cancel_requested session_id=%s pending_ids=%s",
            session_id,
            len(pending_ids),
        )
        return {
            "messages": [AIMessage(content="Поиск остановлен по запросу пользователя.")],
            "iterations_left": 0,
            "candidates": pending_candidates,
            "cancelled": True,
            "session_id": session_id,
        }
    llm_with_tools = llm.bind_tools(sub_tools)
    msgs: List[AnyMessage] = list(state.get("messages", []))
    iters_left = int(state.get("iterations_left", 0))
    msgs.append(SystemMessage(content=f"Итераций осталось: {iters_left}"))
    # Force selection on the last try.
    if iters_left <= 1:
        msgs.append(SystemMessage(content=SUB_AGENT_LAST_TRY_PROMPT))
    response = llm_with_tools.invoke(msgs)
    next_state = {
        "messages": [response],
        "iterations_left": int(state.get("iterations_left", 0)) - 1,
        "session_id": state.get("session_id"),
    }
    logger.info(
        "node=sub_agent_node done iterations_left=%s tool_calls=%s",
        next_state["iterations_left"],
        bool(getattr(response, "tool_calls", None)),
    )
    return next_state


def _sub_router(state: SubState) -> Literal["tools", "report"]:
    msgs = state.get("messages", [])
    last = msgs[-1] if msgs else None
    has_calls = bool(getattr(last, "tool_calls", None))
    # Allow tool execution even on the last try (iterations_left can become 0 after decrement).
    if has_calls and int(state.get("iterations_left", 0)) >= 0:
        logger.info("node=_sub_router route=tools iterations_left=%s", state.get("iterations_left"))
        return "tools"
    logger.info("node=_sub_router route=report iterations_left=%s", state.get("iterations_left"))
    return "report"


@timed_node("sub.report")
def sub_report_node(state: SubState) -> SubState:
    msgs: List[AnyMessage] = list(state.get("messages", []))
    if state.get("cancelled"):
        candidates: List[Dict[str, Any]] = list(state.get("candidates", []) or [])
        report_note = f"Поиск прерван - сохранено {len(candidates)} кандидатов."
        task = str(state.get("task") or "")
        _write_sub_agent_report(report_note, msgs, task)
        logger.info("node=sub_report_node cancelled report_len=%s", len(report_note))
        return {"report": "", "cancelled": True}
    # LLM-based reports are disabled; main agent will interpret tool payloads.
    # --- previously:
    # tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    # summary_lines = [
    #     f"tool_calls={len(tool_msgs)}",
    #     f"iterations_left={state.get('iterations_left')}",
    # ]
    # report_context = "\n".join(summary_lines)
    # report_search = llm.invoke(
    #     [
    #         SystemMessage(content=SEARCH_REPORT_PROMPT),
    #         HumanMessage(content=f"История сообщений:\n{report_context}"),
    #     ]
    # ).content
    #
    # selected_ids: List[str] = list(state.get("selected_ids", []) or [])
    # report_candidates = ""
    # if selected_ids:
    #     candidates = fetch_candidates_by_ids(selected_ids)
    #     compact_payload = [
    #         {
    #             "id": str(c.get("id")),
    #             "full_name": " ".join(
    #                 [p for p in [c.get("last_name"), c.get("first_name"), c.get("middle_name")] if p]
    #             ),
    #             "residence_area": c.get("residence_area"),
    #             "birth_date": c.get("birth_date"),
    #             "education_count": c.get("education_count"),
    #             "education_text": _short(str(c.get("education_text") or "")),
    #             "work_text": _short(str(c.get("work_text") or "")),
    #             "extra_info_text": _short(str(c.get("extra_info_text") or "")),
    #         }
    #         for c in candidates
    #         if isinstance(c, dict)
    #     ]
    #     task = str(state.get("task") or "")
    #     report_candidates = llm.invoke(
    #         [
    #             SystemMessage(content=CANDIDATE_REPORT_PROMPT),
    #             HumanMessage(
    #                 content=(
    #                     f"Запрос пользователя:\n{task}\n\n"
    #                     f"Кандидаты:\n{json.dumps(compact_payload, ensure_ascii=False, default=str)}"
    #                 )
    #             ),
    #         ]
    #     ).content
    #
    # report = "Отчет по поиску:\n{search}".format(search=report_search)
    # if report_candidates:
    #     report = report + "\n\nОтчет по кандидатам:\n{cands}".format(cands=report_candidates)
    report = ""
    task = str(state.get("task") or "")
    _write_sub_agent_report(report, msgs, task)
    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    logger.info("node=sub_report_node done tool_calls=%s", len(tool_msgs))
    return {"report": report}


@timed_node("sub.result")
def sub_result_node(state: SubState) -> SubState:
    """Build the final result for the main agent using State-only data."""
    max_candidates = max(1, int(os.getenv("SUB_AGENT_MAX_CANDIDATES", "5")))
    candidates: List[Dict[str, Any]] = list(state.get("candidates", []) or [])
    candidates = candidates[:max_candidates]
    result = {
        "candidates": candidates,
        "cancelled": bool(state.get("cancelled")),
    }
    logger.info(
        "node=sub_result_node done candidates=%s",
        len(result["candidates"]),
    )
    return result



sub_workflow = StateGraph(SubState)
sub_workflow.add_node("agent", sub_agent_node)
sub_workflow.add_node("tools", sub_tools_node)
sub_workflow.add_node("report", sub_report_node)
sub_workflow.add_node("result", sub_result_node)

sub_workflow.set_entry_point("agent")
sub_workflow.add_conditional_edges("agent", _sub_router, {"tools": "tools", "report": "report"})
sub_workflow.add_edge("tools", "agent")
sub_workflow.add_edge("report", "result")
sub_workflow.add_edge("result", END)

sub_graph = sub_workflow.compile()


# ------------------------
# Main-agent tool: delegate to sub-agent
# ------------------------


@tool
def find_candidates(
    task: str,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Dict[str, Any]:
    """Подбор кандидатов по текстовому запросу, возвращает IDs и отчет."""
    iters = int(os.getenv("SUB_AGENT_MAX_ITERS", "12"))
    session_id = state.get("session_id")
    _set_search_in_progress(session_id, True)
    logger.info("tool=find_candidates start iters=%s task=%r", iters, _short(task))
    # Pass the main chat history as a list of messages (not a formatted string).
    # Important: exclude tool-call messages to avoid invalid tool-call/tool-result pairs
    # when this history is later used in an independent LLM call.
    context_msgs: List[AnyMessage] = []
    main_msgs = state.get("messages") or []
    for m in main_msgs[-10:]:
        if isinstance(m, HumanMessage):
            context_msgs.append(m)
        elif isinstance(m, AIMessage):
            # If this AIMessage contains tool calls, keep only its textual content.
            if getattr(m, "tool_calls", None):
                if m.content:
                    context_msgs.append(AIMessage(content=m.content))
            else:
                context_msgs.append(m)
    init_messages: List[AnyMessage] = [
        SystemMessage(content=SUB_AGENT_SYSTEM_PROMPT),
        HumanMessage(content=task),
    ]
    try:
        result: SubState = sub_graph.invoke(
            {
                "task": task,
                # Pass the main-agent chat history for sub-agent context.
                "context": context_msgs,
                "iterations_left": iters,
                "messages": init_messages,
                "session_id": session_id,
            }
        )
    finally:
        _set_search_in_progress(session_id, False)
    payload = {
        "report": result.get("report", ""),
        "candidates": [],
        "cancelled": bool(result.get("cancelled")),
    }
    full_candidates = result.get("candidates", [])
    saved_info = _extract_saved_info(result.get("messages") or [])
    compact_candidates: List[Dict[str, Any]] = []
    if isinstance(full_candidates, list):
        for candidate in full_candidates:
            if not isinstance(candidate, dict):
                continue
            cid = candidate.get("id")
            if cid and str(cid) in saved_info:
                compact = dict(saved_info[str(cid)])
                if "full_name" not in compact:
                    full_name = _candidate_full_name(candidate)
                    if full_name:
                        compact["full_name"] = full_name
                compact_candidates.append(compact)
                continue
            compact = {"id": str(cid)} if cid else {}
            full_name = _candidate_full_name(candidate)
            if full_name:
                compact["full_name"] = full_name
            if compact:
                compact_candidates.append(compact)
    payload["candidates"] = compact_candidates
    if session_id and session_id in SESSIONS and isinstance(full_candidates, list):
        SESSIONS[session_id]["pending_candidates"] = full_candidates
        pending_ids = [str(item.get("id")) for item in full_candidates if isinstance(item, dict) and item.get("id")]
        SESSIONS[session_id]["pending_candidate_ids"] = pending_ids
    logger.info(
        "tool=find_candidates done candidates=%s report_len=%s",
        len(payload.get("candidates") or []),
        len(payload["report"] or ""),
    )
    if Command is not None:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=json.dumps(payload, ensure_ascii=False, default=str),
                        tool_call_id=tool_call_id,
                        name="find_candidates",
                    )
                ]
            }
        )

    return payload

@tool
def get_candidate_by_id(candidates_ids: List[Union[UUID, str]]) -> Dict:
    """Детали кандидатов по списку ID."""

    if not candidates_ids:
        logger.info("get_candidate_by_id tool: candidates_ids were not given")
        return {"result": "candidates ids were not given"}

    # Преобразуем все ID в строки для запроса
    str_ids = []
    for cid in candidates_ids:
        if isinstance(cid, UUID):
            str_ids.append(str(cid))
        elif isinstance(cid, str):
            try:
                # Проверяем что строка - валидный UUID
                UUID(cid)
                str_ids.append(cid)
            except ValueError:
                logger.warning(f"Invalid UUID string: {cid}")
                continue
        else:
            logger.warning(f"Unsupported ID type: {type(cid)}")
            continue

    if not str_ids:
        logger.info("get_candidate_by_id tool: no valid IDs provided")
        return {"result": "no valid UUIDs provided"}

    # Создаем параметры для запроса
    placeholders = ", ".join([f":id_{i}" for i in range(len(str_ids))])
    params = {f"id_{i}": cid for i, cid in enumerate(str_ids)}

    query = text(
        f"""
        SELECT
            id::text,
            date_received,
            last_name,
            first_name,
            middle_name,
            previous_last_name,
            sex,
            birth_date,
            birth_place,
            snils,
            passport_number,
            passport_issued,
            phone_mobile,
            phone_2,
            phone_3,
            email_1,
            email_2,
            email_upgo,
            residence_area,
            appointment_date,
            dismissal_date,
            confirmed_experience_years,
            source_info,
            education_text,
            education_count,
            work_text,
            extra_info_text
        FROM candidates
        WHERE id::text IN ({placeholders})
    """
    )

    result = {"result": {}}

    # Инициализируем результат для всех valid ID
    for cid in str_ids:
        result["result"][cid] = {
            "requested_id": cid,
            "status": "not found",
            "data": None,
        }

    try:
        global engine
        with engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()

        for row in rows:
            row_dict = dict(row)
            candidate_id = row_dict["id"]  # уже строка

            # Преобразуем данные в CandidateOut
            try:
                candidate_data = CandidateOut(**row_dict).model_dump()
                candidate_data = _compact_candidate(candidate_data)

                result["result"][candidate_id]["status"] = "found"
                result["result"][candidate_id]["data"] = candidate_data

                logger.info(f"get_candidate_by_id tool: {candidate_id} was found")
            except Exception as e:
                result["result"][candidate_id]["status"] = "error processing data"
                result["result"][candidate_id]["error"] = str(e)
                logger.error(f"Error processing candidate {candidate_id}: {e}")

    except Exception as e:
        # В случае ошибки БД
        error_msg = str(e)
        result["error"] = error_msg
        logger.error(f"get_candidate_by_id tool: database error: {error_msg}")

    return result

main_tools = [find_candidates, get_candidate_by_id]
main_tool_node = ToolNode(main_tools)


@timed_node("main.tools")
def main_tools_node(state: MainState) -> MainState:
    return main_tool_node.invoke(state)


@timed_node("main.agent")
def main_agent_node(state: MainState) -> MainState:
    logger.info("node=main_agent_node start messages=%s", len(state.get("messages", []) or []))
    llm_with_tools = llm.bind_tools(main_tools)
    response = llm_with_tools.invoke(state["messages"])
    next_state = {"messages": [response], "session_id": state.get("session_id")}
    logger.info("node=main_agent_node done tool_calls=%s", bool(getattr(response, "tool_calls", None)))
    return next_state


def _main_router(state: MainState) -> Literal["tools", "end"]:
    msgs = state.get("messages", [])
    last = msgs[-1] if msgs else None
    if getattr(last, "tool_calls", None):
        logger.info("node=_main_router route=tools")
        return "tools"
    logger.info("node=_main_router route=end")
    return "end"


def _main_after_tools_router(state: MainState) -> Literal["agent", "end"]:
    msgs = state.get("messages", [])
    session_id = state.get("session_id")
    if _is_cancel_requested(session_id):
        logger.info("node=_main_after_tools_router route=end cancel_requested=true")
        return "end"
    cancelled = False
    for msg in reversed(msgs):
        if isinstance(msg, ToolMessage) and _tool_name(msg) == "find_candidates":
            payload = _parse_tool_payload(msg.content)
            cancelled = bool(payload.get("cancelled")) if isinstance(payload, dict) else False
            break
    if cancelled:
        logger.info("node=_main_after_tools_router route=end cancelled=true")
        return "end"
    logger.info("node=_main_after_tools_router route=agent")
    return "agent"


main_workflow = StateGraph(MainState)
main_workflow.add_node("agent", main_agent_node)
main_workflow.add_node("tools", main_tools_node)
main_workflow.set_entry_point("agent")
main_workflow.add_conditional_edges("agent", _main_router, {"tools": "tools", "end": END})
main_workflow.add_conditional_edges("tools", _main_after_tools_router, {"agent": "agent", "end": END})
graph_app = main_workflow.compile()


# ------------------------
# FastAPI
# ------------------------


app = FastAPI(title="SQL-HR Chat API")


@app.on_event("startup")
def log_first_candidates_on_startup() -> None:
    """Log a few rows to verify DB connectivity on startup."""
    try:
        with SessionLocal() as session:
            rows = session.scalars(select(C).limit(5)).all()
        logger.info("startup db_check candidates_count=%s", len(rows))
        for idx, row in enumerate(rows, start=1):
            logger.info(
                "startup candidate[%s] id=%s last_name=%r first_name=%r residence_area=%r",
                idx,
                getattr(row, "id", None),
                getattr(row, "last_name", None),
                getattr(row, "first_name", None),
                getattr(row, "residence_area", None),
            )
    except Exception:
        logger.exception("startup db_check failed")

class SessionData(TypedDict):
    """In-memory session storage.

    Stores both chat history and the history of candidate selections returned to the user.
    """

    messages: List[AnyMessage]
    candidate_sets: List[List[Dict[str, Any]]]
    candidate_index: int
    pending_candidates: List[Dict[str, Any]]
    pending_candidate_ids: List[str]
    cancel_requested: bool
    search_in_progress: bool
    speed_report_path: Optional[str]


# session_id -> session data
SESSIONS: Dict[str, SessionData] = {}


def _is_cancel_requested(session_id: Optional[str]) -> bool:
    if not session_id:
        return False
    session_data = SESSIONS.get(session_id)
    if not session_data:
        return False
    return bool(session_data.get("cancel_requested"))


def _set_search_in_progress(session_id: Optional[str], value: bool) -> None:
    if not session_id:
        return
    session_data = SESSIONS.get(session_id)
    if not session_data:
        return
    session_data["search_in_progress"] = value


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    candidates_index: int = -1
    candidates_total: int = 0
    report: str = ""


class CandidateSetsResponse(BaseModel):
    session_id: str
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    candidates_index: int = -1
    candidates_total: int = 0


class CandidateCurrentResponse(BaseModel):
    session_id: str
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    pending: bool = False


class StopSearchResponse(BaseModel):
    session_id: str
    stop_requested: bool
    message: str = ""


def _extract_find_candidates_payload(messages: List[AnyMessage]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        name = _tool_name(msg)
        if name != "find_candidates":
            continue
        parsed = _parse_tool_payload(msg.content)
        if isinstance(parsed, dict):
            payload = parsed
    return payload


def _find_tool_pair(
    messages: List[AnyMessage], tool_name: str
) -> tuple[Optional[AIMessage], Optional[ToolMessage]]:
    last_call: Optional[AIMessage] = None
    last_result: Optional[ToolMessage] = None
    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for call in msg.tool_calls:
                if isinstance(call, dict) and call.get("name") == tool_name:
                    last_call = msg
        elif isinstance(msg, ToolMessage) and _tool_name(msg) == tool_name:
            last_result = msg
    return last_call, last_result


@app.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {
            "messages": [SystemMessage(content=MAIN_AGENT_SYSTEM_PROMPT)],
            "candidate_sets": [],
            "candidate_index": -1,
            "pending_candidates": [],
            "pending_candidate_ids": [],
            "cancel_requested": False,
            "search_in_progress": False,
            "speed_report_path": None,
        }

    session_data = SESSIONS[session_id]
    history = session_data["messages"]
    history.append(HumanMessage(content=req.message))

    token = CURRENT_SESSION_ID.set(session_id)
    try:
        _init_speed_report(session_id)
        state: MainState = await run_in_threadpool(
            graph_app.invoke, {"messages": history, "session_id": session_id}
        )
    finally:
        CURRENT_SESSION_ID.reset(token)
    all_messages = state["messages"]

    ai_msgs = [m for m in all_messages if isinstance(m, AIMessage)]
    answer = ai_msgs[-1].content if ai_msgs else ""

    tool_payload = _extract_find_candidates_payload(all_messages)
    report = tool_payload.get("report", "") if isinstance(tool_payload, dict) else ""
    cancelled = bool(tool_payload.get("cancelled")) if isinstance(tool_payload, dict) else False

    if cancelled:
        tool_call_msg, tool_result_msg = _find_tool_pair(all_messages, "find_candidates")
        if tool_call_msg and tool_result_msg:
            history.append(tool_call_msg)
            history.append(tool_result_msg)
        answer = ""

    # Persist only the last AI message (keeps session small).
    if ai_msgs and not cancelled:
        history.append(ai_msgs[-1])

    # Save candidate set history in the session.
    candidates_list: List[Dict[str, Any]] = []
    payload_candidates = tool_payload.get("candidates") if isinstance(tool_payload, dict) else None
    pending_candidates = session_data.get("pending_candidates") or []
    pending_candidate_ids = session_data.get("pending_candidate_ids") or []
    if isinstance(payload_candidates, list) and payload_candidates:
        if _are_compact_candidates(payload_candidates) and pending_candidates:
            candidates_list = pending_candidates
        else:
            candidates_list = [item for item in payload_candidates if isinstance(item, dict)]
    elif pending_candidates:
        candidates_list = pending_candidates
    if candidates_list:
        session_data["candidate_sets"].append(candidates_list)
        session_data["candidate_index"] = len(session_data["candidate_sets"]) - 1
    if pending_candidates:
        session_data["pending_candidates"] = []
    if pending_candidate_ids:
        session_data["pending_candidate_ids"] = []

    idx = int(session_data.get("candidate_index", -1))
    total = len(session_data.get("candidate_sets", []))
    response_candidates: List[Dict[str, Any]] = []
    if candidates_list:
        response_candidates = candidates_list

    session_data["cancel_requested"] = False

    return ChatResponse(
        session_id=session_id,
        answer=answer,
        candidates=response_candidates,
        candidates_index=idx,
        candidates_total=total,
        report=report if isinstance(report, str) else "",
    )


@app.get("/session/{session_id}/candidates", response_model=CandidateSetsResponse)
async def get_candidates_set(
    session_id: str,
    index: Optional[int] = None,
    direction: Optional[int] = None,
) -> CandidateSetsResponse:
    """Navigate candidate set history for a session.

    - If `direction` is provided, moves current index by that delta (-1/ +1).
    - If `index` is provided, jumps to that index.
    - If neither is provided, returns the current set.
    """
    session_data = SESSIONS.get(session_id)
    if not session_data:
        return CandidateSetsResponse(
            session_id=session_id,
            candidates=[],
            candidates_index=-1,
            candidates_total=0,
        )

    sets = session_data.get("candidate_sets", [])
    total = len(sets)
    idx = int(session_data.get("candidate_index", -1))
    if total == 0:
        session_data["candidate_index"] = -1
        return CandidateSetsResponse(
            session_id=session_id,
            candidates=[],
            candidates_index=-1,
            candidates_total=0,
        )

    if direction is not None:
        idx = idx + int(direction)
    elif index is not None:
        idx = int(index)

    idx = max(0, min(idx, total - 1))
    session_data["candidate_index"] = idx

    return CandidateSetsResponse(
        session_id=session_id,
        candidates=sets[idx],
        candidates_index=idx,
        candidates_total=total,
    )


@app.get("/session/{session_id}/candidates/current", response_model=CandidateCurrentResponse)
async def get_current_candidates(session_id: str) -> CandidateCurrentResponse:
    session_data = SESSIONS.get(session_id)
    if not session_data:
        return CandidateCurrentResponse(session_id=session_id, candidates=[], pending=False)

    pending_candidates = session_data.get("pending_candidates") or []
    pending_candidate_ids = session_data.get("pending_candidate_ids") or []
    if session_data.get("search_in_progress"):
        if pending_candidate_ids and not pending_candidates:
            pending_candidates = await run_in_threadpool(
                fetch_candidates_by_ids, pending_candidate_ids
            )
            session_data["pending_candidates"] = pending_candidates
        return CandidateCurrentResponse(
            session_id=session_id,
            candidates=pending_candidates,
            pending=True,
        )
    if pending_candidate_ids:
        if not pending_candidates:
            pending_candidates = await run_in_threadpool(
                fetch_candidates_by_ids, pending_candidate_ids
            )
            session_data["pending_candidates"] = pending_candidates
        return CandidateCurrentResponse(
            session_id=session_id,
            candidates=pending_candidates,
            pending=True,
        )
    if pending_candidates:
        return CandidateCurrentResponse(
            session_id=session_id,
            candidates=pending_candidates,
            pending=True,
        )

    return CandidateCurrentResponse(
        session_id=session_id,
        candidates=[],
        pending=False,
    )


@app.post("/session/{session_id}/stop", response_model=StopSearchResponse)
async def stop_search(session_id: str) -> StopSearchResponse:
    session_data = SESSIONS.get(session_id)
    if not session_data:
        return StopSearchResponse(
            session_id=session_id,
            stop_requested=False,
            message="session not found",
        )
    session_data["cancel_requested"] = True
    return StopSearchResponse(
        session_id=session_id,
        stop_requested=True,
        message="stop requested",
    )


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8010"))
    uvicorn.run(app, host="0.0.0.0", port=port)

from __future__ import annotations

import ast
import json
import logging
import os
import uuid
from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

from fastapi import FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import and_, create_engine, or_, select
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
    SEARCH_REPORT_PROMPT,
    SUB_AGENT_LAST_TRY_PROMPT,
    SUB_AGENT_SYSTEM_PROMPT,
)

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)


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
        use_vllm = os.getenv("USE_VLLM", "True") == "True"

        vllm_model = os.getenv("VLLM_MODEL")
        vllm_key = os.getenv("VLLM_KEY")
        vllm_base_url = os.getenv("VLLM_BASE_URL", "http://vllm:8001/v1")

        proxy_model = os.getenv("PROXY_MODEL")
        proxy_api_key = os.getenv("PROXY_API_KEY")
        proxy_base_url = os.getenv("PROXY_BASE_URL", "https://api.openai.com/v1")

        llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1024"))

        logger.info(
            "LLM init: use_vllm=%s, vllm_model=%r, vllm_base_url=%r, proxy_model=%r, proxy_base_url=%r, proxy_key_set=%s, llm_max_tokens=%s",
            use_vllm,
            vllm_model,
            vllm_base_url,
            proxy_model,
            proxy_base_url,
            bool(proxy_api_key),
            llm_max_tokens,
        )

        if use_vllm:
            if not vllm_model:
                raise RuntimeError("USE_VLLM=true, но VLLM_MODEL не задан")
            self.llm = ChatOpenAI(
                model=vllm_model,
                api_key=vllm_key,
                base_url=vllm_base_url,
                temperature=0,
                max_tokens=llm_max_tokens,
            )
        else:
            if not proxy_model:
                raise RuntimeError("USE_VLLM=false, но PROXY_MODEL не задан")
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
    """Structured DB search specification for the sub-agent."""

    city: Optional[str] = Field(default=None, description="Город/регион")
    desired_position: Optional[str] = Field(default=None, description="Желаемая позиция")
    min_salary_rub: Optional[int] = Field(default=None, description="Мин. зарплата (руб)")
    max_salary_rub: Optional[int] = Field(default=None, description="Макс. зарплата (руб)")
    ready_to_relocate: Optional[bool] = Field(default=None, description="Готовность к релокации")
    keywords_any: List[str] = Field(default_factory=list, description="Хотя бы одно ключевое слово в опыте")
    keywords_all: List[str] = Field(default_factory=list, description="Все ключевые слова в опыте")
    keywords_not: List[str] = Field(default_factory=list, description="Ключевые слова, которых не должно быть")
    limit: int = Field(5, ge=1, le=5, description="Сколько строк вернуть (<=5)")


def _short(txt: Optional[str], limit: int = 500) -> Optional[str]:
    if not txt:
        return txt
    return txt if len(txt) <= limit else (txt[:limit] + "…")


def get_from_query(spec: QuerySpec, session: Session) -> List[CandidateOut]:
    clauses = []
    if spec.city:
        clauses.append(C.city.ilike(f"%{spec.city}%"))
    if spec.desired_position:
        clauses.append(C.desired_position.ilike(f"%{spec.desired_position}%"))
    if spec.min_salary_rub is not None:
        clauses.append(C.expected_salary_rub >= spec.min_salary_rub)
    if spec.max_salary_rub is not None:
        clauses.append(C.expected_salary_rub <= spec.max_salary_rub)
    if spec.ready_to_relocate is not None:
        clauses.append(C.ready_to_relocate == spec.ready_to_relocate)

    for kw in (spec.keywords_all or []):
        clauses.append(C.work_experience.ilike(f"%{kw}%"))

    any_clauses = [C.work_experience.ilike(f"%{kw}%") for kw in (spec.keywords_any or [])]
    if any_clauses:
        clauses.append(or_(*any_clauses))

    not_clauses = [~C.work_experience.ilike(f"%{kw}%") for kw in (spec.keywords_not or [])]
    if not_clauses:
        clauses.append(and_(*not_clauses))

    stmt = select(C)
    if clauses:
        stmt = stmt.where(and_(*clauses))
    stmt = stmt.limit(int(spec.limit or 5))

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
        return [CandidateOut.model_validate(r).model_dump() for r in rows]


# ------------------------
# LangGraph state + reducers
# ------------------------


def add_messages(left: List[AnyMessage], right: List[AnyMessage]) -> List[AnyMessage]:
    return left + right


def add_unique_ids(left: List[str], right: List[str]) -> List[str]:
    out: List[str] = list(left)
    seen = set(out)
    for x in right:
        s = str(x)
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


class MainState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]


class SubState(TypedDict, total=False):
    task: str
    context: List[AnyMessage]
    iterations_left: int
    messages: Annotated[List[AnyMessage], add_messages]
    selected_ids: Annotated[List[str], add_unique_ids]
    last_pool: List[str]
    report: str
    candidates: List[Dict[str, Any]]
    need_user: bool
    user_question: str


# ------------------------
# Sub-agent tools (exactly 3)
# ------------------------


@tool
def clarify_with_main(
    question: str,
    state: Annotated[dict, InjectedState],
) -> Dict[str, Any]:
    """Ask the main agent for clarification using the main agent's message history.

    The sub-agent receives the main chat history in `state['context']` as a List[AnyMessage].
    We consult a separate LLM call that *thinks it is the main agent*.
    The clarification request is delivered as a ToolMessage ("тул спрашивает уточняющий вопрос: …").
    """

    context_msgs = state.get("context")
    if not isinstance(context_msgs, list):
        context_msgs = []

    # Build a valid tool-message pair for providers that require tool_call_id matching.
    call_id = f"clarify_{uuid.uuid4().hex}"
    tool_question = f"тул спрашивает уточняющий вопрос: {question}".strip()
    tool_call_stub = AIMessage(
        content="",
        additional_kwargs={
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "clarify_with_main", "arguments": "{}"},
                }
            ]
        },
    )

    msgs: List[AnyMessage] = [
        SystemMessage(
            content=(
                MAIN_AGENT_SYSTEM_PROMPT
                + "\n\nТы отвечаешь как основной агент на уточняющий вопрос, полученный от инструмента. "
                + "Если ответа в истории нет, укажи need_user=true и сформулируй один вопрос пользователю." 
                + "\n\nВерни строго JSON формата: "
                + "{\"answer\": <строка>, \"need_user\": <true/false>, \"user_question\": <строка>}"
            )
        ),
        *context_msgs,
        tool_call_stub,
        ToolMessage(content=tool_question, tool_call_id=call_id),
    ]
    try:
        raw = llm.invoke(msgs).content
        parsed = _parse_tool_payload(raw)
        if isinstance(parsed, dict):
            return {
                "answer": str(parsed.get("answer", "")),
                "need_user": bool(parsed.get("need_user", False)),
                "user_question": str(parsed.get("user_question", "")),
            }
        return {"answer": str(raw), "need_user": True, "user_question": question}
    except Exception:
        logger.exception("clarify_with_main failed")
        return {
            "answer": "Не удалось уточнить детали автоматически.",
            "need_user": True,
            "user_question": question,
        }


@tool
def db_search(
    spec: QuerySpec,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Any:
    """Search the DB and return up to 5 candidates (compact payload for LLM).

    Also saves ids from the latest search into `last_pool` in the sub-agent state.
    """
    with SessionLocal() as session:
        rows = get_from_query(spec, session=session)
    payload = [
        {
            "id": str(c.id),
            "desired_position": c.desired_position,
            "city": c.city,
            "expected_salary_rub": c.expected_salary_rub,
            "ready_to_relocate": c.ready_to_relocate,
            "resume_updated_at": c.resume_updated_at.isoformat() if c.resume_updated_at else None,
            "work_experience": _short(c.work_experience),
            "last_company": c.last_company,
            "last_job_title": c.last_job_title,
        }
        for c in rows
    ]
    result = {"count": len(payload), "candidates": payload}

    # If Command is available, update state directly (no extra collector/finalize nodes).
    if Command is not None:
        last_pool = [str(x.get("id")) for x in payload if isinstance(x, dict) and x.get("id")]
        return Command(
            update={
                "last_pool": last_pool,
                "messages": [ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tool_call_id)],
            }
        )

    return result


@tool
def save_candidate_ids(
    ids: List[str],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Any:
    """Save chosen candidate ids (sub-agent will return them to the main agent).

    Also accumulates ids into `selected_ids` in the sub-agent state.
    """
    normalized: List[str] = []
    seen: set[str] = set()
    for cid in ids or []:
        s = str(cid)
        if s not in seen:
            normalized.append(s)
            seen.add(s)
    result = {"saved": normalized, "saved_count": len(normalized)}

    if Command is not None:
        return Command(
            update={
                "selected_ids": normalized,
                "messages": [ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tool_call_id)],
            }
        )

    return result


sub_tools = [clarify_with_main, db_search, save_candidate_ids]
sub_tool_node = ToolNode(sub_tools)


# ------------------------
# Sub-agent nodes
# ------------------------


def sub_agent_node(state: SubState) -> SubState:
    llm_with_tools = llm.bind_tools(sub_tools)
    msgs: List[AnyMessage] = list(state.get("messages", []))
    # Force selection on the last try.
    if int(state.get("iterations_left", 0)) <= 1:
        msgs.append(SystemMessage(content=SUB_AGENT_LAST_TRY_PROMPT))
    response = llm_with_tools.invoke(msgs)
    return {
        "messages": [response],
        "iterations_left": int(state.get("iterations_left", 0)) - 1,
    }


def _sub_router(state: SubState) -> Literal["tools", "report"]:
    msgs = state.get("messages", [])
    last = msgs[-1] if msgs else None
    has_calls = bool(getattr(last, "tool_calls", None))
    # Allow tool execution even on the last try (iterations_left can become 0 after decrement).
    if has_calls and int(state.get("iterations_left", 0)) >= 0:
        return "tools"
    return "report"


def sub_report_node(state: SubState) -> SubState:
    msgs: List[AnyMessage] = list(state.get("messages", []))
    # Keep report compact: include only tool usage and selected ids.
    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    summary_lines = [
        f"tool_calls={len(tool_msgs)}",
        f"iterations_left={state.get('iterations_left')}",
    ]
    report_context = "\n".join(summary_lines)
    report = llm.invoke(
        [
            SystemMessage(content=SEARCH_REPORT_PROMPT),
            HumanMessage(content=f"Контекст процесса:\n{report_context}"),
        ]
    ).content
    return {"report": report}


def sub_result_node(state: SubState) -> SubState:
    """Build the final result for the main agent using State-only data."""
    ids: List[str] = list(state.get("selected_ids", []) or [])
    last_pool: List[str] = list(state.get("last_pool", []) or [])

    # Fallback: if the agent never saved ids, take ids from the last db_search.
    if not ids and last_pool:
        ids = last_pool[:5]

    candidates = fetch_candidates_by_ids(ids)
    return {
        "selected_ids": ids,
        "candidates": candidates,
    }



sub_workflow = StateGraph(SubState)
sub_workflow.add_node("agent", sub_agent_node)
sub_workflow.add_node("tools", sub_tool_node)
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
) -> Dict[str, Any]:
    """Delegate candidate search to the sub-agent."""
    iters = int(os.getenv("SUB_AGENT_MAX_ITERS", "3"))
    # Pass the main chat history as a list of messages (not a formatted string).
    # Important: exclude tool-call messages to avoid invalid tool-call/tool-result pairs
    # when this history is later used in an independent LLM call.
    context_msgs: List[AnyMessage] = []
    main_msgs = state.get("messages") or []
    for m in main_msgs[-24:]:
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
    result: SubState = sub_graph.invoke(
        {
            "task": task,
            # Pass the main-agent chat history so clarify_with_main can answer from it.
            "context": context_msgs,
            "iterations_left": iters,
            "messages": init_messages,
        }
    )
    return {
        "selected_ids": result.get("selected_ids", []),
        "candidates": result.get("candidates", []),
        "report": result.get("report", ""),
    }


main_tools = [find_candidates]
main_tool_node = ToolNode(main_tools)


def main_agent_node(state: MainState) -> MainState:
    llm_with_tools = llm.bind_tools(main_tools)
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def _main_router(state: MainState) -> Literal["tools", "end"]:
    msgs = state.get("messages", [])
    last = msgs[-1] if msgs else None
    if getattr(last, "tool_calls", None):
        return "tools"
    return "end"


main_workflow = StateGraph(MainState)
main_workflow.add_node("agent", main_agent_node)
main_workflow.add_node("tools", main_tool_node)
main_workflow.set_entry_point("agent")
main_workflow.add_conditional_edges("agent", _main_router, {"tools": "tools", "end": END})
main_workflow.add_edge("tools", "agent")
graph_app = main_workflow.compile()


# ------------------------
# FastAPI
# ------------------------


app = FastAPI(title="SQL-HR Chat API")

# session_id -> message history
SESSIONS: Dict[str, List[AnyMessage]] = {}


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    report: str = ""


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


@app.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())
    if session_id not in SESSIONS:
        SESSIONS[session_id] = [SystemMessage(content=MAIN_AGENT_SYSTEM_PROMPT)]

    history = SESSIONS[session_id]
    history.append(HumanMessage(content=req.message))

    state: MainState = graph_app.invoke({"messages": history})
    all_messages = state["messages"]

    ai_msgs = [m for m in all_messages if isinstance(m, AIMessage)]
    answer = ai_msgs[-1].content if ai_msgs else ""

    # Persist only the last AI message (keeps session small).
    if ai_msgs:
        history.append(ai_msgs[-1])

    tool_payload = _extract_find_candidates_payload(all_messages)
    candidates = tool_payload.get("candidates") if isinstance(tool_payload, dict) else None
    report = tool_payload.get("report", "") if isinstance(tool_payload, dict) else ""

    return ChatResponse(
        session_id=session_id,
        answer=answer,
        candidates=candidates if isinstance(candidates, list) else [],
        report=report if isinstance(report, str) else "",
    )


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

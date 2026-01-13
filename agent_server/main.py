from __future__ import annotations

import os
import json
import ast
import uuid
import logging
from typing import TypedDict, List, Dict, Optional, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, Field

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from typing_extensions import Annotated

from fastapi import FastAPI

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    SystemMessage,
    AIMessage,
    ToolMessage,
)
from langchain_core.tools import tool

# наши модели и узлы
from candidates import CandidateScore, TopCandidates, CandidateOut
from nodes import (
    node_generate_accents,
    node_choose_candidates,
    node_add_candidates,
    node_rate_candidates,
    node_return_candidates,
    node_ask_next,
    node_test_db,
)

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)


class CandidateState(TypedDict, total=False):
    task: str
    extra_task: str
    accents: List[str]
    raw_candidates: List[TopCandidates]
    ranked: List[CandidateScore]


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

class API():
    llm = None

    def __init__(self):
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
                logger.error("USE_VLLM=true, но VLLM_MODEL не задан")
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
                logger.error("USE_VLLM=false, но PROXY_MODEL не задан")
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


def fetch_candidates_by_ids(engine, ids: List[UUID | str]) -> Dict[str, Dict[str, Any]]:
    """
    Берём из БД реальные поля по списку айдишников.
    Возвращаем словарь {id: {...факты из базы...}}
    """
    if not ids:
        return {}

    placeholders = ", ".join(f":id_{i}" for i in range(len(ids)))
    params = {f"id_{i}": str(cid) for i, cid in enumerate(ids)}

    query = text(
        f"""
        SELECT
            id,
            sex,
            expected_salary_rub,
            desired_position,
            city,
            ready_to_relocate,
            ready_for_business_trips,
            employment_type,
            work_schedule,
            work_experience,
            last_company,
            last_job_title,
            education_level_and_university,
            resume_updated_at,
            has_car
        FROM candidates
        WHERE id IN ({placeholders})
    """
    )

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().all()

    return {str(row["id"]): dict(row) for row in rows}


def _node_generate_accents(state: CandidateState) -> CandidateState:
    return node_generate_accents(state, llm)


def _node_choose_candidates(state: CandidateState) -> CandidateState:
    with Session(bind=engine, expire_on_commit=False) as s:
        return node_choose_candidates(state, llm, s)


def _node_add_candidates(state: CandidateState) -> CandidateState:
    with Session(bind=engine, expire_on_commit=False) as s:
        return node_add_candidates(
            state,
            llm,
            s,
            target_n=15,  # сколько хотим на акцент
            batch_limit=30,  # размер batch из БД за итерацию
            max_iters=3,  # ограничитель итераций
        )


def _node_rate_candidates(state: CandidateState) -> CandidateState:
    return node_rate_candidates(state, llm, top_n=10)


def _node_return_candidates(state: CandidateState) -> CandidateState:
    # node_return_candidates сам пишет result.txt, но нам важен state["ranked"]
    return node_return_candidates(state)


def _node_test_db(state: CandidateState) -> CandidateState:
    with Session(bind=engine, expire_on_commit=False) as s:
        return node_test_db(state, s)

candidate_workflow = StateGraph(CandidateState)

candidate_workflow.add_node("test_db", _node_test_db)
candidate_workflow.add_node("generate_accents", _node_generate_accents)
candidate_workflow.add_node("choose_candidates", _node_choose_candidates)
candidate_workflow.add_node("add_candidates", _node_add_candidates)
candidate_workflow.add_node("rate_candidates", _node_rate_candidates)
candidate_workflow.add_node("return_candidates", _node_return_candidates)
candidate_workflow.add_node("ask_next", node_ask_next)

candidate_workflow.set_entry_point("test_db")

candidate_workflow.add_edge("test_db", "generate_accents")
candidate_workflow.add_edge("generate_accents", "choose_candidates")
candidate_workflow.add_edge("choose_candidates", "add_candidates")
candidate_workflow.add_edge("add_candidates", "rate_candidates")
candidate_workflow.add_edge("choose_candidates", "rate_candidates")
candidate_workflow.add_edge("rate_candidates", "return_candidates")
candidate_workflow.add_edge("return_candidates", "ask_next")

candidate_graph = candidate_workflow.compile()


# -----------------------------
# Тул для LLM: choose_candidates
# -----------------------------
@tool
def choose_candidates(query: str) -> List[str]:
    """
    Инструмент для LLM: запускает граф подбора кандидатов и
    возвращает список id найденных кандидатов (строками).

    LLM видит только список id, а полные данные мы достаём на бэке.
    В get_candidate_by_id используются id отсюда.
    """
    state: CandidateState = candidate_graph.invoke({"task": query})
    ranked: List[CandidateScore] = state.get("ranked", [])  # может отсутствовать
    ids = [str(item.candidate.id) for item in ranked]
    logger.info("choose_candidates tool: picked %d candidates", len(ids))
    return ids

@tool
def get_candidate_by_id(candidates_ids: List[Union[UUID, str]]) -> Dict:
    """
    Тул для ии-агента, который ищет информацию о кандидатах в базе данных по данным id

    :param candidates_ids: список id (UUID объекты, которые вернул choose_candidates. Не просто число)
    :return: словарь с результатами поиска
    """

    if not candidates_ids:
        logger.info("get_candidate_by_id tool: candidates_ids were not given")
        return {'result': 'candidates ids were not given'}

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
        return {'result': 'no valid UUIDs provided'}

    # Создаем параметры для запроса
    placeholders = ", ".join([f":id_{i}" for i in range(len(str_ids))])
    params = {f"id_{i}": cid for i, cid in enumerate(str_ids)}

    query = text(f"""
        SELECT
            id::text, 
            sex,
            expected_salary_rub,
            desired_position,
            city,
            ready_to_relocate,
            ready_for_business_trips,
            employment_type,
            work_schedule,
            work_experience,
            last_company,
            last_job_title,
            education_level_and_university,
            resume_updated_at,
            has_car
        FROM candidates
        WHERE id::text IN ({placeholders})
    """)

    result = {'result': {}}

    # Инициализируем результат для всех valid ID
    for cid in str_ids:
        result['result'][cid] = {
            'requested_id': cid,
            'status': 'not found',
            'data': None
        }

    try:
        global engine
        with engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()

        for row in rows:
            row_dict = dict(row)
            candidate_id = row_dict['id']  # уже строка

            # Преобразуем данные в CandidateOut
            try:
                candidate_data = CandidateOut(**row_dict).model_dump()

                result['result'][candidate_id]['status'] = 'found'
                result['result'][candidate_id]['data'] = candidate_data

                logger.info(f"get_candidate_by_id tool: {candidate_id} was found")
            except Exception as e:
                result['result'][candidate_id]['status'] = 'error processing data'
                result['result'][candidate_id]['error'] = str(e)
                logger.error(f"Error processing candidate {candidate_id}: {e}")

    except Exception as e:
        # В случае ошибки БД
        error_msg = str(e)
        result['error'] = error_msg
        logger.error(f"get_candidate_by_id tool: database error: {error_msg}")

    return result

def add_messages(left: List[AnyMessage], right: List[AnyMessage]) -> List[AnyMessage]:
    return left + right


class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]


tools = [choose_candidates, get_candidate_by_id]
tool_node = ToolNode(tools)

def agent_node(state: AgentState) -> AgentState:
    """LLM-агент, умеющий вызывать инструменты."""
    llm_with_tools = llm.bind_tools(tools)
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def router(state: AgentState) -> Literal["tools", "end"]:
    """Маршрутизатор: решает, нужно ли идти в ToolNode."""
    last_msg = state["messages"][-1]
    if getattr(last_msg, "tool_calls", None):
        return "tools"
    return "end"

main_workflow = StateGraph(AgentState)
main_workflow.add_node("agent", agent_node)
main_workflow.add_node("tools", tool_node)

main_workflow.set_entry_point("agent")
main_workflow.add_conditional_edges(
    "agent",
    router,
    {
        "tools": "tools",
        "end": END,
    },
)
# после tools всегда возвращаемся к agent за финальным ответом
main_workflow.add_edge("tools", "agent")

graph_app = main_workflow.compile()


app = FastAPI(title="SQL-HR Chat API")

# Память диалогов: session_id -> история сообщений LangChain
SESSIONS: Dict[str, List[AnyMessage]] = {}


CHAT_SYSTEM_PROMPT = (
    "Ты - HR-помощник. Твоя задача — помочь пользователю максимально чётко "
    "сформулировать запрос к кандидату. "
    "Когда человек просит подобрать кандидатов (или информации достаточно), "
    "вызови инструмент choose_candidates. "
    "Если пользователь явно просит детали по конкретным кандидатам или эти детали "
    "нужны, чтобы ответить на его вопрос, используй get_candidate_by_id только для "
    "этих кандидатов (UUID бери из результата choose_candidates). "
    "Не запрашивай через get_candidate_by_id всех кандидатов подряд — пользователь "
    "и так видит профили последних кандидатов у себя на экране. "
    "Говори по-русски, дружелюбно, без лишней воды."
)


class ChatRequest(BaseModel):
    # Клиент МОЖЕТ не прислать session_id (первый запрос) —
    # тогда мы сгенерируем его сами.
    session_id: Optional[str] = None
    message: str


class ChatResponse(BaseModel):
    # Всегда возвращаем session_id, чтобы клиент мог его сохранить
    session_id: str
    answer: str
    # id -> данные кандидата из БД
    candidates: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


def _extract_candidate_ids(messages: List[AnyMessage]) -> List[str]:
    ids: List[str] = []
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.name == "choose_candidates":
            content = msg.content
            parsed: List[str] = []

            if isinstance(content, list):
                parsed = [str(x) for x in content]
            elif isinstance(content, str):
                # LangChain кладёт результат тула как строку; пытаемся распарсить список/JSON
                try:
                    data = json.loads(content)
                    if isinstance(data, list):
                        parsed = [str(x) for x in data]
                    elif isinstance(data, dict):
                        cand_list = data.get("candidates")
                        if isinstance(cand_list, list):
                            parsed = [str(x) for x in cand_list]
                except Exception:
                    try:
                        data = ast.literal_eval(content)
                        if isinstance(data, list):
                            parsed = [str(x) for x in data]
                        elif isinstance(data, dict):
                            cand_list = data.get("candidates")
                            if isinstance(cand_list, list):
                                parsed = [str(x) for x in cand_list]
                    except Exception:
                        logger.warning(
                            "Не удалось распарсить содержимое choose_candidates: %s",
                            content,
                        )

            if parsed:
                ids.extend(parsed)
    return ids


@app.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())
    if session_id not in SESSIONS:
        SESSIONS[session_id] = [SystemMessage(content=CHAT_SYSTEM_PROMPT)]

    history = SESSIONS[session_id]

    history.append(HumanMessage(content=req.message))

    state: AgentState = graph_app.invoke({"messages": history})
    all_messages = state["messages"]

    ai_msgs = [m for m in all_messages if isinstance(m, AIMessage)]
    answer = ai_msgs[-1].content if ai_msgs else ""

    if ai_msgs:
        history.append(ai_msgs[-1])

    candidate_ids = _extract_candidate_ids(all_messages)
    candidate_profiles = fetch_candidates_by_ids(engine, candidate_ids)

    return ChatResponse(
        session_id=session_id,
        answer=answer,
        candidates=candidate_profiles,
    )


@app.get("/health")
async def health() -> Dict[str, str]:
    """Простая проверка готовности сервиса."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

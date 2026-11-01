"""Provider compatibility tests: HTTP is simulated; application graph is real."""
import importlib.util
import json
import sys
import types
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

AGENT_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app_module():
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(AGENT_DIR))
        patch.setenv("MODEL", "offline-test")
        patch.setenv("API_KEY", "offline-test")
        patch.setenv("SAVE_LOGS", "False")
        reranker = types.ModuleType("reranker")
        reranker.rerank_candidates = lambda query, candidates, top_k=5: candidates[:top_k]
        patch.setitem(sys.modules, "reranker", reranker)
        spec = importlib.util.spec_from_file_location("sqlhr_provider_test_app", AGENT_DIR / "main.py")
        module = importlib.util.module_from_spec(spec)
        patch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        yield module
        module.engine.dispose()


def completion(message, finish_reason="stop"):
    return httpx.Response(200, json={
        "id": "offline-completion", "object": "chat.completion", "created": 0,
        "model": "offline-test", "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })


def test_query_builder_uses_provider_tool_calls_instead_of_json_schema(app_module, monkeypatch):
    bundle = {"ideal_spec": {"keywords_any": ["Западн"]},
              "match_spec": {"keywords_any": ["Западн"]},
              "fallback_spec": {"keywords_any": ["Западн"]}}

    def provider(request):
        payload = json.loads(request.content)
        if "response_format" in payload:
            # Actual failure observed with the Caila adapter: fenced JSON.
            return completion({"role": "assistant", "content": "```json\n" + json.dumps(bundle) + "\n```"})
        name = payload["tools"][0]["function"]["name"]
        return completion({"role": "assistant", "content": None, "tool_calls": [{
            "id": "offline-tool", "type": "function",
            "function": {"name": name, "arguments": json.dumps(bundle)},
        }]}, "tool_calls")

    actual_specs = []

    def search(**kwargs):
        actual_specs.append(kwargs["match_spec"])
        return {"summary": "", "ideal": {}, "match": {}, "fallback": {}}, []

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        model = ChatOpenAI(model="offline-test", api_key="offline-test", http_client=client)
        monkeypatch.setattr(app_module, "llm", model)
        monkeypatch.setattr(app_module, "_db_search_impl", search)
        result = app_module.sub_agent_node({"task": "Найди кандидатов в Западном районе", "iterations_left": 2, "messages": []})
    assert result["iterations_left"] == 1
    assert actual_specs[0].keywords_any == ["Западн"]


def test_chat_preserves_search_failure_instead_of_reporting_no_candidates(app_module, monkeypatch):
    from fastapi.testclient import TestClient

    def fail_search(state):
        raise ValueError("query generation failed")

    answers = iter([
        AIMessage(content="", tool_calls=[{"name": "find_candidates", "args": {"task": "Найди кандидатов"}, "id": "offline-find"}]),
        AIMessage(content="Кандидаты не найдены."),
    ])
    model = types.SimpleNamespace(bind_tools=lambda tools: types.SimpleNamespace(invoke=lambda messages: next(answers)))
    monkeypatch.setattr(app_module, "llm", model)
    monkeypatch.setattr(app_module, "sub_graph", types.SimpleNamespace(invoke=fail_search))
    response = TestClient(app_module.app).post("/", json={"message": "Найди кандидатов"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["candidates"] == []
    assert "ошибка" in payload["answer"].lower()
    assert "недоступен" in payload["answer"].lower()
    assert "упростить запрос" not in payload["answer"].lower()

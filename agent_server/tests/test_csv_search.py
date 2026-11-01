"""Offline regression tests: real SQL and agent graph, synthetic candidates only."""
import importlib.util
import sys
import types
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

AGENT_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app_module():
    # Only the external model reranker is replaced; SQL, schemas and graph are real.
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(AGENT_DIR))
        patch.setenv("MODEL", "offline-test")
        patch.setenv("API_KEY", "offline-test")
        patch.setenv("SAVE_LOGS", "False")
        reranker = types.ModuleType("reranker")
        reranker.rerank_candidates = lambda query, candidates, top_k=5: candidates[:top_k]
        patch.setitem(sys.modules, "reranker", reranker)
        spec = importlib.util.spec_from_file_location("sql_hr_test_app", AGENT_DIR / "main.py")
        module = importlib.util.module_from_spec(spec)
        patch.setitem(sys.modules, "sql_hr_test_app", module)
        spec.loader.exec_module(module)
        yield module
        module.engine.dispose()


@pytest.fixture
def database(app_module, monkeypatch):
    from candidates import Base
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def unicode_lower(connection, record):
        # SQLite lower() is ASCII-only; PostgreSQL handles Cyrillic.
        connection.create_function("lower", 1, lambda value: value.lower() if value is not None else None)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(app_module, "SessionLocal", factory)
    with factory() as session:
        yield session
    engine.dispose()


def add_candidate(app, session, name, **fields):
    candidate = app.C(id=uuid.uuid4(), last_name=name, **fields)
    session.add(candidate)
    session.commit()
    return candidate


@pytest.mark.parametrize("schema", ["QuerySpec", "QuerySpecLite"])
@pytest.mark.parametrize("query, field, matching, failing", [
    ({"age_from": 26, "age_to": 36}, "birth_date", date(date.today().year - 30, 1, 1), date(1950, 1, 1)),
    ({"education_count": 2}, "education_count", 2, 1),
    ({"citizenship": "РФ"}, "citizenship", "РФ", "Казахстан"),
    ({"citizenship": "Казахстан"}, "citizenship", "Казахстан", "РФ"),
    ({"citizenship": "другое"}, "citizenship", "Казахстан", "РФ"),
    ({"status": "резервист"}, "status", "резервист", "снят"),
    ({"ready_to_work": "годен"}, "ready_to_work", "годен", "не годен"),
    ({"confirmed_experience_years_min": 5}, "confirmed_experience_years", 6, 2),
])
def test_explicit_filter_rejects_unknown_and_mismatch(app_module, database, schema, query, field, matching, failing):
    add_candidate(app_module, database, "подходит", **{field: matching})
    add_candidate(app_module, database, "не подходит", **{field: failing})
    add_candidate(app_module, database, "неизвестно")
    result = app_module.get_from_query(getattr(app_module, schema)(**query), database)
    assert [c.last_name for c in result] == ["подходит"]


def test_default_filters_allow_unknown_but_reject_known_mismatch(app_module, database):
    add_candidate(app_module, database, "неизвестно")
    add_candidate(app_module, database, "подходит", birth_date=date(1995, 1, 1), education_count=1,
                  citizenship="РФ", status="резервист", ready_to_work="годен")
    add_candidate(app_module, database, "не подходит", status="снят")
    result = app_module.get_from_query(app_module.QuerySpec(), database)
    assert {c.last_name for c in result} == {"неизвестно", "подходит"}


def test_city_and_profession_are_both_required(app_module, database):
    # Put >20 unrelated rows first: the matching row must survive SQL selection.
    for i in range(25):
        add_candidate(app_module, database, f"other-{i}", residence_area="Казань", work_text="Сетевой администратор")
    add_candidate(app_module, database, "other-job", residence_area="Москва", work_text="Бухгалтер")
    wanted = add_candidate(app_module, database, "wanted", residence_area="Москва", work_text="Сетевой администратор",
                           source_file="synthetic.csv", source_row=28)
    spec = app_module.QuerySpec(keywords_all=["сетев", "администратор"], residence_keywords_any=["москв"])
    result = app_module.get_from_query(spec, database)
    assert [c.id for c in result] == [wanted.id]
    assert (result[0].source_file, result[0].source_row) == ("synthetic.csv", 28)


def install_query_builder(app, monkeypatch, bundle):
    from langchain_core.messages import AIMessage

    class OfflineLLM:
        def with_structured_output(self, schema, **kwargs):
            return types.SimpleNamespace(invoke=lambda messages: bundle)

        def bind_tools(self, tools):
            return types.SimpleNamespace(invoke=lambda messages: AIMessage(content="", tool_calls=[{
                "name": "find_candidates", "args": {"task": "Найди кандидатов с английским B2"}, "id": "offline-call",
            }]))

    monkeypatch.setattr(app, "llm", OfflineLLM())


def test_unsupported_requirement_stops_search_and_reaches_chat(app_module, database, monkeypatch):
    from fastapi.testclient import TestClient
    add_candidate(app_module, database, "unknown-language")
    bundle = app_module.QuerySpecBundle(ideal_spec={}, match_spec={}, fallback_spec={},
                                        unsupported_requirements=["английский язык B2"])
    install_query_builder(app_module, monkeypatch, bundle)
    monkeypatch.setenv("SUB_AGENT_MAX_ITERS", "1")
    response = TestClient(app_module.app).post("/", json={"message": "Найди кандидатов с английским B2"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["candidates"] == []
    assert "английский" in payload["answer"]
    assert "данных" in payload["answer"]
    assert "B1" not in payload["answer"]


def test_explicit_field_empty_in_dataset_reports_missing_data(app_module, database, monkeypatch):
    add_candidate(app_module, database, "unknown-status")
    bundle = app_module.QuerySpecBundle(ideal_spec={"status": "резервист"}, match_spec={"status": "резервист"}, fallback_spec={})
    install_query_builder(app_module, monkeypatch, bundle)
    result = app_module.sub_graph.invoke({"task": "Найди резервистов", "iterations_left": 1, "messages": [], "session_id": None})
    assert result.get("candidates") == []
    assert "статус" in result.get("report", "").lower()
    assert "данных" in result.get("report", "").lower()


def test_hh_csv_mapping_to_search_preserves_source_row(app_module, database):
    loader_dir = AGENT_DIR.parent / "loader"
    spec = importlib.util.spec_from_file_location("hh_loader", loader_dir / "load_csv.py")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    csv_path = loader_dir / "examples" / "candidates_hh.csv"
    mapping_path = loader_dir / "mappings" / "candidates_hh.yaml"
    fields = loader.load_mapping(mapping_path)
    _, loaded, rejected, notes = loader.read_csv(csv_path, loader.mapping_delimiter(mapping_path), fields)
    assert rejected == []
    assert notes == []
    assert len(loaded) == 3
    for source_row, record in loaded:
        add_candidate(app_module, database, record.pop("last_name"), **record,
                      source_file=csv_path.name, source_row=source_row)
    query = app_module.QuerySpec(keywords_all=["сетев", "администратор"], residence_keywords_any=["москв"])
    result = app_module.get_from_query(query, database)
    assert [(c.last_name, c.source_file, c.source_row) for c in result] == [
        ("synthetic-001", "candidates_hh.csv", 2),
    ]


def test_missing_field_is_not_reported_when_values_exist_but_do_not_match(app_module, database):
    add_candidate(app_module, database, "known-status", status="снят")
    query = app_module.QuerySpec(status="резервист")
    assert app_module._unavailable_fields(query, database) == []
    assert app_module.get_from_query(query, database) == []


def test_empty_database_is_not_misreported_as_missing_field(app_module, database):
    assert app_module._unavailable_fields(app_module.QuerySpec(status="резервист"), database) == []


def test_fallback_cannot_drop_explicit_match_filter(app_module, database):
    add_candidate(app_module, database, "known", status="резервист")
    add_candidate(app_module, database, "unknown")
    strict = app_module.QuerySpec(status="резервист")
    _, result = app_module._db_search_impl(strict, strict, app_module.QuerySpecLite(), None)
    assert [c["last_name"] for c in result] == ["known"]


def test_repeated_iteration_cannot_drop_initial_match_filter(app_module, database, monkeypatch):
    add_candidate(app_module, database, "known", status="резервист")
    add_candidate(app_module, database, "unknown")
    responses = iter([
        app_module.QuerySpecBundle(ideal_spec={"status": "резервист"}, match_spec={"status": "резервист"}, fallback_spec={}),
        app_module.QuerySpecBundle(ideal_spec={}, match_spec={}, fallback_spec={}),
    ])
    monkeypatch.setattr(app_module, "llm", types.SimpleNamespace(with_structured_output=lambda schema, **kwargs:
                        types.SimpleNamespace(invoke=lambda messages: next(responses))))
    result = app_module.sub_graph.invoke({"task": "Найди резервистов", "iterations_left": 2, "messages": [], "session_id": None})
    assert [c["last_name"] for c in result["candidates"]] == ["known"]


@pytest.mark.parametrize("required_values, variant_values, age", [
    ({"age_to": 40}, {"age_from": 70}, 50),
    ({"age_from": 30}, {"age_to": 28}, 29),
])
def test_extra_age_bound_cannot_reverse_explicit_age_requirement(app_module, database, required_values, variant_values, age):
    add_candidate(app_module, database, "wrong-age", birth_date=date(date.today().year - age, 1, 1))
    required = app_module.QuerySpec(**required_values)
    _, result = app_module._db_search_impl(app_module.QuerySpec(**variant_values), required, app_module.QuerySpecLite(), None)
    assert result == []

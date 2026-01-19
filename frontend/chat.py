import streamlit as st
import requests
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

SERVER_URL = os.getenv("SERVER_URL")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.5"))
EXECUTOR = ThreadPoolExecutor(max_workers=1)

if "messages" not in st.session_state:
    st.session_state.messages = []

if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "pending_future" not in st.session_state:
    st.session_state.pending_future = None
if "stop_requested" not in st.session_state:
    st.session_state.stop_requested = False

st.set_page_config(page_title="SQL-HR", layout="wide")

st.title("SQL-HR")


def _normalize_candidates(payload):
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _render_candidates(candidates):
    if not candidates:
        return
    st.markdown("**Кандидаты:**")
    for candidate in candidates:
        cand_id = str(candidate.get("id") or "")
        with st.container(border=True):
            full_name = " ".join(
                [
                    part
                    for part in [
                        candidate.get("last_name"),
                        candidate.get("first_name"),
                        candidate.get("middle_name"),
                    ]
                    if part
                ]
            )
            st.markdown(f"#### {full_name or 'Кандидат'}")

            if cand_id:
                st.markdown(f"**ID:** `{cand_id}`")
            if "residence_area" in candidate and candidate.get("residence_area"):
                st.markdown(f"**Район проживания:** {candidate.get('residence_area')}")

            with st.expander("Показать остальные поля"):
                for field, value in candidate.items():
                    if field in (
                        "last_name",
                        "first_name",
                        "middle_name",
                        "residence_area",
                    ):
                        continue
                    st.markdown(f"**{field}:** {value}")


def _poll_candidates(session_id):
    if not SERVER_URL or not session_id:
        return [], False
    try:
        base = (SERVER_URL or "").rstrip("/")
        url = f"{base}/session/{session_id}/candidates/current"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        r_json = r.json()
        return _normalize_candidates(r_json.get("candidates", []) or []), bool(r_json.get("pending"))
    except Exception:
        return [], False


def _post_chat(payload):
    r = requests.post(SERVER_URL, json=payload)
    r.raise_for_status()
    return r.json()


def _post_stop(session_id):
    if not SERVER_URL or not session_id:
        return False
    base = (SERVER_URL or "").rstrip("/")
    url = f"{base}/session/{session_id}/stop"
    r = requests.post(url, timeout=10)
    r.raise_for_status()
    return True


def _finalize_pending_response():
    pending_future = st.session_state.pending_future
    if not pending_future or not pending_future.done():
        return False
    reply = ""
    candidates = []
    try:
        r_json = pending_future.result()
        st.session_state.session_id = r_json.get("session_id", st.session_state.session_id)
        reply = r_json.get("answer", "")
        candidates = _normalize_candidates(r_json.get("candidates", []) or [])
    except Exception as e:
        reply = f"Ошибка при запросе к серверу: {e}"
        candidates = []
    st.session_state.pending_future = None
    st.session_state.stop_requested = False
    if reply or candidates:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": reply,
                "candidates": candidates,
            }
        )
    return True


# ---------------- LEFT: CHAT (основная область) ----------------
st.subheader("Чат")

_finalize_pending_response()

pending_future = st.session_state.pending_future
pending_in_flight = pending_future is not None and not pending_future.done()

for m in st.session_state.messages:
    content = m["content"]
    if m["role"] == "assistant" and "tool_call" in content:
        continue
    with st.chat_message(m["role"]):
        if m["role"] == "assistant":
            _render_candidates(m.get("candidates") or [])
        st.markdown(content)

if pending_in_flight:
    @st.fragment(run_every=POLL_INTERVAL)
    def _search_status():
        pending_future = st.session_state.pending_future
        if not pending_future:
            return
        if pending_future.done():
            if _finalize_pending_response():
                st.rerun()
            return
        polled, is_pending = _poll_candidates(st.session_state.session_id)
        with st.chat_message("assistant"):
            _render_candidates(polled)
            if not is_pending:
                return
            stop_disabled = st.session_state.stop_requested
            if st.button("Остановить поиск", disabled=stop_disabled, key="stop_search"):
                try:
                    if _post_stop(st.session_state.session_id):
                        st.session_state.stop_requested = True
                except Exception:
                    st.session_state.stop_requested = False
            if st.session_state.stop_requested:
                st.markdown("Останавливаю поиск...")
            else:
                st.markdown("Ищу по базе...")

    _search_status()

prompt = st.chat_input("Введите запрос", disabled=pending_in_flight)

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})

    if not SERVER_URL:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": "SERVER_URL не задан в переменных окружения.",
            }
        )
    else:
        try:
            if not st.session_state.session_id:
                st.session_state.session_id = str(uuid.uuid4())
            payload = {"session_id": st.session_state.session_id, "message": prompt}
            st.session_state.pending_future = EXECUTOR.submit(_post_chat, payload)
            st.session_state.stop_requested = False
        except Exception as e:
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": f"Ошибка при запросе к серверу: {e}",
                }
            )

    st.rerun()

import streamlit as st
import requests
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

SERVER_URL = os.getenv("SERVER_URL")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.5"))

if "messages" not in st.session_state:
    st.session_state.messages = []

if "session_id" not in st.session_state:
    st.session_state.session_id = None

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
        return []
    try:
        base = (SERVER_URL or "").rstrip("/")
        url = f"{base}/session/{session_id}/candidates/current"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        r_json = r.json()
        return _normalize_candidates(r_json.get("candidates", []) or [])
    except Exception:
        return []


def _post_chat(payload):
    r = requests.post(SERVER_URL, json=payload)
    r.raise_for_status()
    return r.json()


# ---------------- LEFT: CHAT (основная область) ----------------
st.subheader("Чат")

for m in st.session_state.messages:
    content = m["content"]
    if m["role"] == "assistant" and "tool_call" in content:
        content = "Ищу по базе..."
    with st.chat_message(m["role"]):
        if m["role"] == "assistant":
            _render_candidates(m.get("candidates") or [])
        st.markdown(content)

prompt = st.chat_input("Введите запрос")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})

    reply = ""
    candidates = []

    if not SERVER_URL:
        reply = "SERVER_URL не задан в переменных окружения."
    else:
        with st.spinner("Отправляю запрос..."):
            try:
                if not st.session_state.session_id:
                    st.session_state.session_id = str(uuid.uuid4())
                payload = {"session_id": st.session_state.session_id, "message": prompt}
                placeholder = st.empty()
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_post_chat, payload)
                    while not future.done():
                        polled = _poll_candidates(st.session_state.session_id)
                        with placeholder.container():
                            with st.chat_message("assistant"):
                                _render_candidates(polled)
                                st.markdown("Ищу по базе...")
                        time.sleep(POLL_INTERVAL)
                    r_json = future.result()
                placeholder.empty()

                st.session_state.session_id = r_json.get("session_id", st.session_state.session_id)

                reply = r_json.get("answer", "")
                candidates = _normalize_candidates(r_json.get("candidates", []) or [])
            except Exception as e:
                reply = f"Ошибка при запросе к серверу: {e}"
                candidates = []

    if reply:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": reply,
                "candidates": candidates,
            }
        )

    st.rerun()

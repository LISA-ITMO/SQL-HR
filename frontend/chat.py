import streamlit as st
import requests
import os

SERVER_URL = os.getenv("SERVER_URL")

if "messages" not in st.session_state:
    st.session_state.messages = []

if "candidates" not in st.session_state:
    st.session_state.candidates = {}

if "candidates_index" not in st.session_state:
    st.session_state.candidates_index = -1

if "candidates_total" not in st.session_state:
    st.session_state.candidates_total = 0

if "session_id" not in st.session_state:
    st.session_state.session_id = None

st.set_page_config(page_title="SQL-HR", layout="wide")

# --- UI styles (кнопки пагинации) ---
st.markdown(
    """
<style>
/* делаем кнопки навигации компактными и "икон-стайл" */
div[data-testid="stSidebar"] div[data-testid="stButton"] > button {
    width: 44px;
    height: 44px;
    border-radius: 999px;
    padding: 0;
    font-size: 18px;
    line-height: 1;
}

/* немного приятнее отключённое состояние */
div[data-testid="stSidebar"] div[data-testid="stButton"] > button:disabled {
    opacity: 0.45;
}

/* выравниваем шапку "Кандидаты" */
.cand-nav {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 6px;
    margin-bottom: 6px;
}
.cand-nav .info {
    opacity: 0.8;
    font-size: 0.9rem;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("SQL-HR")


def _normalize_candidates(payload):
    """Normalize server payload to dict: id -> candidate dict."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        out = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            cid = item.get("id")
            if cid:
                out[str(cid)] = item
        return out
    return {}


# ---------------- LEFT: CHAT (основная область) ----------------
st.subheader("Чат")

for m in st.session_state.messages:
    content = m["content"]
    if m["role"] == "assistant" and "tool_call" in content:
        content = "Ищу по базе..."
    with st.chat_message(m["role"]):
        st.markdown(content)

prompt = st.chat_input("Введите запрос")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})

    reply = ""
    candidates = {}

    if not SERVER_URL:
        reply = "SERVER_URL не задан в переменных окружения."
    else:
        with st.spinner("Отправляю запрос..."):
            try:
                payload = {"session_id": st.session_state.session_id, "message": prompt}
                r = requests.post(SERVER_URL, json=payload)
                r.raise_for_status()
                r_json = r.json()

                st.session_state.session_id = r_json.get("session_id", st.session_state.session_id)

                reply = r_json.get("answer", "")
                candidates = _normalize_candidates(r_json.get("candidates", []) or [])
                st.session_state.candidates_index = int(r_json.get("candidates_index", -1) or -1)
                st.session_state.candidates_total = int(r_json.get("candidates_total", 0) or 0)

            except Exception as e:
                reply = f"Ошибка при запросе к серверу: {e}"
                candidates = {}
                st.session_state.candidates_index = -1
                st.session_state.candidates_total = 0

    st.session_state.candidates = candidates

    if reply:
        st.session_state.messages.append({"role": "assistant", "content": reply})

    st.rerun()


# ---------------- RIGHT: CANDIDATES (в сайдбаре = отдельный скролл) ----------------
with st.sidebar:
    st.subheader("Кандидаты")

    idx = int(st.session_state.candidates_index or -1)
    total = int(st.session_state.candidates_total or 0)
    can_navigate = bool(SERVER_URL) and bool(st.session_state.session_id) and total > 0

    # Навигация (красивее)
    nav1, nav2, nav3 = st.columns([1, 1, 3])

    with nav1:
        prev_clicked = st.button(
            "◀",
            disabled=(not can_navigate) or (idx <= 0),
            key="cand_prev",
            use_container_width=True,
        )

    with nav2:
        next_clicked = st.button(
            "▶",
            disabled=(not can_navigate) or (idx >= total - 1),
            key="cand_next",
            use_container_width=True,
        )

    with nav3:
        if total > 0 and idx >= 0:
            st.markdown(f"<div class='info'>Подборка <b>{idx + 1}</b> / {total}</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='info'>Подборок пока нет</div>", unsafe_allow_html=True)

    if prev_clicked or next_clicked:
        direction = -1 if prev_clicked else 1
        try:
            base = (SERVER_URL or "").rstrip("/")
            url = f"{base}/session/{st.session_state.session_id}/candidates"
            r = requests.get(url, params={"direction": direction}, timeout=15)
            r.raise_for_status()
            r_json = r.json()

            st.session_state.candidates = _normalize_candidates(r_json.get("candidates", []) or [])
            st.session_state.candidates_index = int(r_json.get("candidates_index", -1) or -1)
            st.session_state.candidates_total = int(r_json.get("candidates_total", 0) or 0)
            st.rerun()

        except Exception as e:
            st.error(f"Не удалось переключить подборку: {e}")

    st.divider()

    if st.session_state.candidates:
        for cand_id, candidate in st.session_state.candidates.items():
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
    else:
        st.caption("Пока кандидатов нет")

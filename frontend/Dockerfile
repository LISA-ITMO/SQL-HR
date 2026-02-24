FROM python:3.11-slim AS base

RUN groupadd -r app && useradd --no-log-init -r -g app app

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . ./
# каталогу конфигов Streamlit и HOME нужны права записи у пользователя app
RUN mkdir -p /app/.streamlit /home/app \
    && chown -R app:app /app/.streamlit /home/app

USER app

ENV PYTHONUNBUFFERED=1
ENV HOME=/home/app

CMD ["streamlit", "run", "chat.py"]

FROM python:3.11-slim AS base

RUN groupadd -r app \
    && useradd --no-log-init -r -m -d /home/app -g app app

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /home/app/hf-cache \
    && chown -R app:app /home/app /app

COPY --chown=app:app . ./

USER app

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]

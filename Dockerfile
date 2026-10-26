FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home bridge
COPY main.py natural_language.py gunicorn.conf.py ./
USER bridge
EXPOSE 8080
CMD ["gunicorn", "--config", "gunicorn.conf.py", "main:app"]

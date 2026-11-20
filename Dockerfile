FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN useradd --create-home app
USER app

HEALTHCHECK --interval=1m --timeout=5s --start-period=30s \
    CMD python -c "import socket; socket.create_connection(('localhost', 4700), 3)"

CMD ["python", "main.py"]

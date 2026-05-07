FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY pyproject.toml ./pyproject.toml

ENV PYTHONPATH=/app/src

ENTRYPOINT ["python", "-m", "cocktailpi_mcp.main"]

FROM python:3.12-slim

WORKDIR /app

# Install package (fastapi + uvicorn are core deps)
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD uvicorn binacci.chain:create_agent_app --factory --host 0.0.0.0 --port ${PORT:-8000}

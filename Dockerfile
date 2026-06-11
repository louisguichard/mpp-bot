FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY data/mpp_supervised_rarity_model.json data/team_aliases.json ./data/
RUN pip install --no-cache-dir ".[bot]"

ENV PORT=8080
CMD exec gunicorn --bind ":${PORT}" --workers 1 --threads 8 --timeout 300 mpp_optimizer.bot_service:app

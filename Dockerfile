FROM python:3.10-slim

WORKDIR /usr/src/app

COPY pyproject.toml uv.lock ./
COPY cazzubot/ cazzubot/
COPY plugins/ plugins/
COPY main.py scripts/ ./

RUN pip install --no-cache-dir uv \
	&& uv sync --no-dev --frozen

ENV PATH="/usr/src/app/.venv/bin:$PATH"

ENTRYPOINT ["python", "./main.py"]

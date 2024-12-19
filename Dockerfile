FROM python:3.13.1-bookworm

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

RUN apt-get update
RUN apt-get install -y libcairo2-dev ffmpeg libreoffice fonts-recommended fonts-noto-cjk ghostscript libfreeimage3 pipx

ENV PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PIP_NO_CACHE_DIR=off \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100 \
  # Poetry's configuration:
  POETRY_NO_INTERACTION=1 \
  PATH="/root/.local/bin:${PATH}"

RUN pipx install poetry==1.8.5
COPY poetry.lock pyproject.toml ./
RUN poetry install --no-interaction --no-root

COPY . .
RUN poetry install --no-interaction

CMD poetry run python media_workflow/worker.py

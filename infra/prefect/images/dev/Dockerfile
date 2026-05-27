FROM prefecthq/prefect:3-python3.13

WORKDIR /opt/mxm-moneymachine

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock ./

RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-root

ENV PYTHONPATH=/Users/mxm/mxm-moneymachine/src


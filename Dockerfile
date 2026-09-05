# Runtime image: docker build -t messpy . && docker run --rm -v "$PWD":/code messpy /code text python
FROM python:3.12-slim AS build
WORKDIR /build
RUN pip install --no-cache-dir build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m build --wheel

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
WORKDIR /code
ENTRYPOINT ["messpy"]
CMD ["--help"]

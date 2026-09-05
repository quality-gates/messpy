# Development image: docker build -f dev.Dockerfile -t messpy-dev . && docker run --rm -it -v "$PWD":/workspace messpy-dev
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git bash && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY . .
RUN pip install --no-cache-dir -e .
CMD ["python", "-m", "unittest", "discover", "-s", "tests"]

FROM python:3.12-slim

WORKDIR /app

# lib/product/Il2CppDumper/linux/Il2CppDumper is x86_64, so build/run this image as linux/amd64.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates libicu76 \
    && curl -fsSL https://dot.net/v1/dotnet-install.sh -o dotnet-install.sh \
    && chmod +x dotnet-install.sh \
    && ./dotnet-install.sh --channel 8.0 --runtime dotnet --install-dir /usr/share/dotnet \
    && ln -s /usr/share/dotnet/dotnet /usr/bin/dotnet \
    && rm dotnet-install.sh \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY lib ./lib

RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir .

ENV PORT=8080
ENV DATA_DIR=/app/data
ENV WORK_DIR=/app/work
ENV IL2CPP_DUMPER_PATH=/app/lib/product/Il2CppDumper/linux/Il2CppDumper
ENV DOTNET_ROOT=/usr/share/dotnet

EXPOSE 8080

CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PORT:-8080} --workers ${WEB_CONCURRENCY:-2} --timeout ${GUNICORN_TIMEOUT_SECONDS:-21600}"]

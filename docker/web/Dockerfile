FROM python:3.6-slim-stretch as builder

WORKDIR /app
COPY requirements.txt ./

RUN python3 -m venv /opt/venv
RUN set -ex \
	&& buildDeps=" \
		build-essential \
		libssl-dev \
		libgmp-dev \
		pkg-config \
		" \
    && apt-get update \
    && apt-get install -y --no-install-recommends $buildDeps \
    && /opt/venv/bin/pip3 install --no-cache-dir -r requirements.txt \
    && find /opt/venv \
        \( -type d -a -name test -o -name tests \) \
        -o \( -type f -a -name '*.pyc' -o -name '*.pyo' \) \
        -exec rm -rf '{}' +

FROM python:3.6-slim-stretch as runner

# Signal handling for PID1 https://github.com/krallin/tini
ENV TINI_VERSION v0.18.0
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini /tini
RUN chmod +x /tini

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
ENV PYTHONUNBUFFERED 1

WORKDIR /app
COPY . .

EXPOSE 8888
ENTRYPOINT ["/tini", "--"]

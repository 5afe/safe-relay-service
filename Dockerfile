FROM python:3.8-slim

ENV PYTHONUNBUFFERED 1
ENV TINI_VERSION v0.19.0

# Signal handling for PID1 https://github.com/krallin/tini
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini /tini
RUN chmod +x /tini

# Create man folders which are required by postgres
RUN for i in {1..8}; do mkdir -p "/usr/share/man/man$i"; done

# Install postgres-client
RUN apt-get update \
      && apt-get install -y git postgresql-client libpq-dev libxml2-dev libxslt-dev python-dev zlib1g-dev

WORKDIR safe-relay-service

# Install Safe relay service
COPY . .

# Install Safe relay service dependencies
RUN set -ex \
      && buildDeps=" \
      build-essential \
      libssl-dev \
      libgmp-dev \
      pkg-config \
      " \
      && apt-get install -y --no-install-recommends $buildDeps \
      && pip install --no-cache-dir -r requirements.txt \
      && apt-get purge -y --auto-remove $buildDeps \
      && rm -rf /var/lib/apt/lists/* \
      && find /usr/local \
      \( -type d -a -name test -o -name tests \) \
      -o \( -type f -a -name '*.pyc' -o -name '*.pyo' \) \
      -exec rm -rf '{}' +

RUN pip check

RUN chmod +x scripts/*.sh

EXPOSE 8888

ENTRYPOINT ["./scripts/wait-for-db.sh", "/tini", "--"]

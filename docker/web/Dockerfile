FROM python:3-slim-stretch

ENV PYTHONUNBUFFERED 1
WORKDIR /app

# Signal handling for PID1 https://github.com/krallin/tini
# We will verify the signature afterwards
ENV TINI_VERSION v0.18.0
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini /tini
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini.asc /tini.asc
RUN chmod +x /tini

COPY requirements.txt ./
RUN set -ex \
	&& buildDeps=" \
		gnupg \
		dirmngr \
		build-essential \
		libssl-dev \
		" \
    && apt-get update \
    && apt-get install -y --no-install-recommends $buildDeps \
    && gpg --keyserver hkp://p80.pool.sks-keyservers.net:80 --recv-keys 595E85A6B1B4779EA4DAAEC70B588DFF0527A9B7 \
    && gpg --verify /tini.asc \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove $buildDeps \
    && rm -rf /var/lib/apt/lists/* \
    && find /usr/local \
        \( -type d -a -name test -o -name tests \) \
        -o \( -type f -a -name '*.pyc' -o -name '*.pyo' \) \
        -exec rm -rf '{}' +

COPY . .

ENTRYPOINT ["/tini", "--"]

#!/bin/bash

set -euo pipefail

if [ "$1" = "develop" -o "$1" = "master" ]; then
    # If image does not exist, don't use cache
    docker pull safeglobal/$DOCKERHUB_PROJECT:$1 && \
    docker build -t $DOCKERHUB_PROJECT -f docker/web/Dockerfile . --cache-from safeglobal/$DOCKERHUB_PROJECT:$1 || \
    docker build -t $DOCKERHUB_PROJECT -f docker/web/Dockerfile .
else
    docker pull safeglobal/$DOCKERHUB_PROJECT:staging && \
    docker build -t $DOCKERHUB_PROJECT -f docker/web/Dockerfile . --cache-from safeglobal/$DOCKERHUB_PROJECT:staging || \
    docker build -t $DOCKERHUB_PROJECT -f docker/web/Dockerfile .
fi
docker tag $DOCKERHUB_PROJECT safeglobal/$DOCKERHUB_PROJECT:$1
docker push safeglobal/$DOCKERHUB_PROJECT:$1
FROM node:9-alpine

RUN apk add --no-cache \
    --virtual .build-deps \
    python2 \
    alpine-sdk \
    && npm config set unsafe-perm true && npm install -g ganache-cli@6.6.0 \
    && apk del --no-cache .build-deps

CMD ["ganache-cli", "-d", "--defaultBalanceEther", "10000000", "-a", "10", "--noVMErrorsOnRPCResponse", "--gasLimit", "10000000000", "--host", "0.0.0.0", "--networkId", "105"]

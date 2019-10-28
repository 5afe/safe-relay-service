FROM node:9-alpine

RUN apk add --no-cache \
    --virtual .build-deps \
    python2 \
    alpine-sdk \
    && npm config set unsafe-perm true && npm install -g ganache-cli@6.6.0 \
    && apk del --no-cache .build-deps

CMD ["ganache-cli", "--account='0xfae42052f82bed612a724fec3632f325f377120592c75bb78adfcceae6470c5a,1000000000000000000000000000000000000000'", "--account='0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d,1000000000000000000000000000000000000000'", "", "-d", "--defaultBalanceEther", "10000000", "-a", "10", "--noVMErrorsOnRPCResponse", "--gasLimit", "10000000000", "--host", "0.0.0.0", "--networkId", "105"]

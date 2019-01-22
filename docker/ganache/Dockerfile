FROM node:9-alpine

RUN npm install -g ganache-cli@beta

CMD ["ganache-cli", "-d", "--defaultBalanceEther", "10000", "-a", "10", "--noVMErrorsOnRPCResponse", "--gasLimit", "8000000", "--host", "0.0.0.0", "--hardfork=constantinople"]

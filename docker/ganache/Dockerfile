FROM node:10-alpine

RUN npm install -g ganache-cli@6.6.0

CMD ["ganache-cli", "-d", "--defaultBalanceEther", "10000", "-a", "10", "--noVMErrorsOnRPCResponse", "--gasLimit", "10000000", "--host", "0.0.0.0"]

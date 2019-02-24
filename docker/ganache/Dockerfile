FROM node:9-alpine

RUN npm install -g ganache-cli@beta

CMD ["ganache-cli", "-i", "1337", "-d", "--defaultBalanceEther", "10000", "-a", "10", "--gasLimit", "8000000", "--host", "0.0.0.0", "--hardfork", "constantinople"]

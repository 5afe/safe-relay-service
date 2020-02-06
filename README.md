[![Build Status](https://travis-ci.org/gnosis/safe-relay-service.svg?branch=master)](https://travis-ci.org/gnosis/safe-relay-service)
[![Coverage Status](https://coveralls.io/repos/github/gnosis/safe-relay-service/badge.svg?branch=master)](https://coveralls.io/github/gnosis/safe-relay-service?branch=master)
![Python 3.8](https://img.shields.io/badge/Python-3.8-blue.svg)
![Django 2](https://img.shields.io/badge/Django-2-blue.svg)

# Gnosis Safe Relay Service
Service for Gnosis Safe Relay

Docs
----
Docs are available on [Readthedocs](https://gnosis-safe.readthedocs.io/en/latest/services/relay.html)
You can open the diagrams explaining _Pre CREATE2_ deployment under `docs/` with [Staruml](http://staruml.io/)

Setup for development (using ganache)
-------------------------------------
This is the recommended configuration for developing and testing the Safe. `docker-compose` is required for
running the project.

Configure the parameters needed on `.env_ganache`. By default the private keys of the accounts are the ones from
Ganache, and the contract addresses are calculated to be the ones deployed by the Relay when the application starts,
so there's no need to configure anything.

More parameters can be added to that file like:
- `SAFE_FIXED_CREATION_COST`: For fixed price in wei for deploying a Safe. If you set `0` you allow Safes to be
deployed for free
- `SAFE_CONTRACT_ADDRESS` to change the Safe's master copy address.
- For more parameters check `base.py` file.

Then:
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml build --force-rm
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

The service should be running in `localhost:8000`

Setup for production relay
--------------------------
This is the recommended configuration for running a production Relay. `docker-compose` is required
for running the project.

Configure the parameters needed on `.env`. These parameters **need to be changed**:
- `ETHEREUM_NODE_URL`: Http/s address of a ethereum node.
- `SAFE_FUNDER_PRIVATE_KEY`: Use a private key for an account with ether on that network. It's used to deploy new Safes.
- `SAFE_TX_SENDER_PRIVATE_KEY`: Same as the `SAFE_FUNDER_PRIVATE_KEY`, but it's used to relay all transactions.

Another parameters can be configured like:
- `SAFE_CONTRACT_ADDRESS`: If you are not using default Gnosis Safe Master Copy.
- `SAFE_FIXED_CREATION_COST`: For fixed price in wei for deploying a Safe. If you set `0` you allow Safes to be
deployed for free
- For more parameters check `base.py` file.

Then:
```bash
docker-compose build --force-rm
docker-compose up
```

The service should be running in `localhost:8000`

For example, to set up a **Göerli** node:
- Set `ETHEREUM_NODE_URL` to `https://goerli.infura.io/v3/YOUR-PROJECT-ID` (if using INFURA)
- Set `SAFE_FUNDER_PRIVATE_KEY` and `SAFE_TX_SENDER_PRIVATE_KEY` to accounts that have Göerli ether. **Don't use
the same account for both**

Run:
```bash
docker-compose build --force-rm
docker-compose up
```

You can test everything is set up:

```bash
curl 'http://localhost:8000/api/v1/about/'
```

Contributors
------------
- Stefan George (stefan@gnosis.pm)
- Denís Graña (denis@gnosis.pm)
- Giacomo Licari (giacomo.licari@gnosis.pm)
- Uxío Fuentefría (uxio@gnosis.pm)

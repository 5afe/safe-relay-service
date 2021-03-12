[![Build Status](https://travis-ci.com/gnosis/safe-relay-service.svg?branch=master)](https://travis-ci.com/gnosis/safe-relay-service)
[![Coverage Status](https://coveralls.io/repos/github/gnosis/safe-relay-service/badge.svg?branch=master)](https://coveralls.io/github/gnosis/safe-relay-service?branch=master)
![Python 3.9](https://img.shields.io/badge/Python-3.9-blue.svg)
![Django 3](https://img.shields.io/badge/Django-3-blue.svg)

# Gnosis Safe Relay Service
This service allows us to have owners of the Safe contract that don’t need to hold any ETH on those owner addresses.
How is this possible? The **Transaction Relay Service** acts as a proxy, paying for the transaction fees and getting it
back due to the transaction architecture we use. It also enables the user to pay for ethereum transactions
using **ERC20 tokens**.

Docs
----
Docs are available on [Gnosis Docs](https://docs.gnosis.io/safe/docs/services_relay/)
You can open the diagrams explaining _Pre CREATE2_ deployment under `docs/` with [Staruml](http://staruml.io/)

Setup for development (using ganache)
-------------------------------------
This is the recommended configuration for developing and testing the Relay service. `docker-compose` is required for
running the project.

Configure the parameters needed on `.env_ganache`. By default the private keys of the accounts are the ones from
Ganache, and the contract addresses are calculated to be the ones deployed by the Relay when the application starts,
so there's no need to configure anything.

More parameters can be added to that file like:
- `SAFE_FIXED_CREATION_COST`: For fixed price in wei for deploying a Safe. If you set `0` you allow Safes to be
deployed for free.
- `SAFE_CONTRACT_ADDRESS` to change the Safe's master copy address.
- For more parameters check `base.py` file.

Then:
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml build --force-rm
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

The service should be running in `localhost:8000`

Setup for production
--------------------
This is the recommended configuration for running a production Relay. `docker-compose` is required
for running the project.

Configure the parameters needed on `.env`. These parameters **need to be changed**:
- `ETHEREUM_NODE_URL`: Http/s address of a ethereum node.
- `SAFE_FUNDER_PRIVATE_KEY`: Use a private key for an account with ether on that network. It's used to deploy new Safes.
- `SAFE_TX_SENDER_PRIVATE_KEY`: Same as the `SAFE_FUNDER_PRIVATE_KEY`, but it's used to relay all transactions.

Another parameters can be configured like:
- `SAFE_CONTRACT_ADDRESS`: If you are not using default Gnosis Safe Master Copy.
- `SAFE_FIXED_CREATION_COST`: For fixed price in wei for deploying a Safe. If you set `0` you allow Safes to be
deployed for free.
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

## Use admin interface
Services come with a basic administration web ui (provided by Django). A user must be created first to
get access:
```bash
docker exec -it safe-relay-service_worker_1 bash
python manage.py createsuperuser
```

Then go to the web browser and navigate to http://localhost:8000/admin/


## Add your custom gas token
Custom tokens can be added as a payment option for the Relay Service from the **admin interface**:
- Navigate to `Tokens` and click `Add`.
- Configure your token and set `Fixed eth conversion` if your token has a fixed price (related to ETH price).
For example, `WETH` token has a `fixed eth conversion` equal to `1`. If not, leave it blank.
- If you want to set up a dynamic oracle after adding your `Token` you need to add a `Price Oracle Ticker`.
You can choose multiple oracle sources. Go back to your `Token` and check if `Eth value` is correct.
- Price is always shown as a reference to Ethereum, so for example `WETH` will have a `eth value` of `1`

Contributors
------------
- Stefan George (stefan@gnosis.pm)
- Denís Graña (denis@gnosis.pm)
- Giacomo Licari (giacomo.licari@gnosis.pm)
- Uxío Fuentefría (uxio@gnosis.pm)

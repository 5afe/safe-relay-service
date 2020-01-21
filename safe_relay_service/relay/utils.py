import logging
from typing import Any, List

from gunicorn import glogging

from gnosis.eth import EthereumClient, EthereumClientProvider


class IgnoreCheckUrl(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        return not ('GET /check/' in message and '200' in message)


class CustomGunicornLogger(glogging.Logger):
    def setup(self, cfg):
        super().setup(cfg)

        # Add filters to Gunicorn logger
        logger = logging.getLogger("gunicorn.access")
        logger.addFilter(IgnoreCheckUrl())


def chunks(l: List[Any], n: int):
    """
    :param l: List
    :param n: Number of elements per chunk
    :return: Yield successive n-sized chunks from l
    """
    for i in range(0, len(l), n):
        yield l[i:i + n]


class EthereumNetwork:

    ethereum_client = EthereumClientProvider()

    def get_network(self):
        """
        return: Name of the current Ethereum network
        """
        network = {
            1: 'mainnet',
            3: 'ropsten',
            4: 'rinkeby',
            42: 'kovan',
        }
        return network.get(self.ethereum_client.w3.net.version, "unknown")

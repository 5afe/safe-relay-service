from django.conf import settings
from logging import getLogger
from sgqlc.endpoint.http import HTTPEndpoint


logger = getLogger(__name__)

url = '{}/subgraphs/name/{}'.format(settings.GRAPH_NODE_EXTERNAL,
                                    settings.SUBGRAPH_NAME)


class GraphQLService:

    def __init__(self):
        self.endpoint = HTTPEndpoint(url)

    def check_trust_connections(self, safe_address: str):
        query = ('{'
                 '  trusts(where: { userAddress: "' + safe_address.lower() + '" }) {'
                 '    id'
                 '  }'
                 '}')

        try:
            # Check if we have enough incoming trust connections
            response = self.endpoint(query)
            incoming_count = len(response['data']['trusts'])
            logger.info('Found {} incoming trust connections for {}'.format(incoming_count,
                                                                            safe_address))
            return incoming_count >= settings.MIN_TRUST_CONNECTIONS

        except:
            return False

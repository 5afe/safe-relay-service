from django.conf import settings
from logging import getLogger
from sgqlc.endpoint.http import HTTPEndpoint


logger = getLogger(__name__)

url = '{}/subgraphs/name/{}'.format(settings.GRAPH_NODE_ENDPOINT,
                                    settings.SUBGRAPH_NAME)


class GraphQLService:

    def __init__(self):
        self.endpoint = HTTPEndpoint(url)

    def check_trust_connections(self, safe_address: str):
        query = ('{'
                 '  trusts(where: { userAddress: "' + safe_address + '" }) {'
                 '    id'
                 '  }'
                 '}')

        try:
            # Check if we have enough incoming trust connections
            response = self.endpoint(query)
            return len(response['data']['trusts']) >= settings.MIN_TRUST_CONNECTIONS

        except:
            return False

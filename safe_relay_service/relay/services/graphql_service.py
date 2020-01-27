from django.conf import settings
from logging import getLogger
from sgqlc.endpoint.http import HTTPEndpoint


logger = getLogger(__name__)

url = '{}/subgraphs/name/{}'.format(settings.GRAPH_NODE_ENDPOINT,
                                    settings.SUBGRAPH_NAME)


class GraphQLService:

    def __init__(self):
        self.endpoint = HTTPEndpoint(url)

    def check_trust_connections(safe_address: str):
        trust_limit = settings.MIN_TRUST_CONNECTIONS

        query = ('{'
                 '  safe(id: "' + safe_address + '") {'
                 '    incoming(first: ' + str(trust_limit) + ') {'
                 '      user { id }'
                 '    }'
                 '  }'
                 '}')

        try:
            response = self.endpoint(query)
            safe = response['data']['safe']

            # Safe does not exist yet
            if not safe:
                return False

            # Check if we have enough incoming trust connections
            return len(safe['incoming']) >= trust_limit

        except:
            return False

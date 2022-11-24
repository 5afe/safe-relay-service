from django.conf import settings
from logging import getLogger
from sgqlc.endpoint.http import HTTPEndpoint

logger = getLogger(__name__)


class GraphQLService:
    def __init__(self):
        url = "{}/subgraphs/name/{}".format(
            settings.GRAPH_NODE_ENDPOINT, settings.SUBGRAPH_NAME
        )
        self.endpoint = HTTPEndpoint(url)

    def check_trust_connections(self, safe_address: str):
        query = (
            "{"
            '  trusts(where: { userAddress: "' + safe_address.lower() + '" }) {'
            "    id"
            "  }"
            "}"
        )

        try:
            # Check if we have enough incoming trust connections
            response = self.endpoint(query)
            incoming_count = len(response["data"]["trusts"])
            logger.info(
                "Found {} incoming trust connections for {}".format(
                    incoming_count, safe_address
                )
            )
            return incoming_count >= settings.MIN_TRUST_CONNECTIONS
        except BaseException as error:
            logger.error(
                'Error "{}" after checking trust connections for {}'.format(
                    str(error), safe_address
                )
            )
            return False

    def check_trust_connections_by_user(self, user_address: str):
        query = (
            "{"
            '  users(where: {id: "' + user_address.lower() + '" }) {'
            "    id safes { id deployed }"
            "  }"
            "}"
        )

        try:
            # Check if we have enough incoming trust connections
            response = self.endpoint(query)
            users = response["data"]["users"]
            if len(users) == 0:
                return False
            safes = users[0]["safes"]
            has_deployed = False
            for safe in safes:
                if safe["deployed"]:
                    has_deployed = True
                    break
            logger.info("Found user {} has a deployed safe".format(user_address))
            return has_deployed
        except BaseException as error:
            logger.error(
                'Error "{}" after checking trust connections for {}'.format(
                    str(error), user_address
                )
            )
            return False

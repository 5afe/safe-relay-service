import ethereum.utils
from django.conf import settings
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from safe_relay_service.safe.models import SafeCreation, SafeFunding
from safe_relay_service.safe.tasks import fund_deployer_task
from safe_relay_service.version import __version__

from .helpers import create_safe_tx
from .serializers import (SafeFundingSerializer,
                          SafeTransactionCreationSerializer)


class AboutView(APIView):
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        if settings.SAFE_FUNDER_PRIVATE_KEY:
            safe_funder_public_key = ethereum.utils.checksum_encode(ethereum.utils.privtoaddr(
                settings.SAFE_FUNDER_PRIVATE_KEY))
        else:
            safe_funder_public_key = None
        content = {
            'name': 'Safe Relay Service',
            'version': __version__,
            'api_version': self.request.version,
            'settings': {
                'ETH_HASH_PREFIX ': settings.ETH_HASH_PREFIX,
                'ETHEREUM_NODE_URL': settings.ETHEREUM_NODE_URL,
                'GAS_STATION_NUMBER_BLOCKS': settings.GAS_STATION_NUMBER_BLOCKS,
                'SAFE_FUNDER_PUBLIC_KEY': safe_funder_public_key,
                'SAFE_PERSONAL_CONTRACT_ADDRESS': settings.SAFE_PERSONAL_CONTRACT_ADDRESS,
                'SAFE_FUNDER_MAX_ETH': settings.SAFE_FUNDER_MAX_ETH,
                'SAFE_FUNDING_CONFIRMATIONS': settings.SAFE_FUNDING_CONFIRMATIONS,
                'SAFE_GAS_PRICE': settings.SAFE_GAS_PRICE,
                'SAFE_CHECK_DEPLOYER_FUNDED_DELAY': settings.SAFE_CHECK_DEPLOYER_FUNDED_DELAY,
                'SAFE_CHECK_DEPLOYER_FUNDED_RETRIES': settings.SAFE_CHECK_DEPLOYER_FUNDED_RETRIES,
            }
        }
        return Response(content)


class SafeTransactionCreationView(CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeTransactionCreationSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            s, owners, threshold = serializer.data['s'], serializer.data['owners'], serializer.data['threshold']
            safe_transaction_data = create_safe_tx(s, owners, threshold)
            return Response(status=status.HTTP_201_CREATED, data=safe_transaction_data.data)
        else:
            http_status = status.HTTP_422_UNPROCESSABLE_ENTITY \
                if 's' in serializer.errors else status.HTTP_400_BAD_REQUEST
            return Response(status=http_status, data=serializer.errors)


class SafeSignalView(APIView):
    permission_classes = (AllowAny,)
    renderer_classes = (JSONRenderer,)

    def get(self, request, address, format=None):
        if not ethereum.utils.check_checksum(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            safe_funding = SafeFunding.objects.get(safe=address)
        except SafeFunding.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        serializer = SafeFundingSerializer(safe_funding)
        return Response(status=status.HTTP_200_OK, data=serializer.data)

    def put(self, request, address, format=None):
        if not ethereum.utils.check_checksum(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            safe_creation = SafeCreation.objects.get(safe=address)
        except SafeCreation.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        fund_deployer_task.delay(address, safe_creation.deployer, safe_creation.gas * safe_creation.gas_price)

        return Response(status=status.HTTP_202_ACCEPTED)

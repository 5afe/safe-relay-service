import ethereum.utils
from django.conf import settings
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from safe_relay_service.safe.models import SafeCreation, SafeFunding, SafeContract, SafeMultisigTx
from safe_relay_service.safe.tasks import fund_deployer_task
from safe_relay_service.version import __version__

from .serializers import (SafeFundingSerializer,
                          SafeTransactionCreationResponseSerializer,
                          SafeTransactionCreationSerializer,
                          SafeMultisigTxSerializer)


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
            safe_creation = SafeCreation.objects.create_safe_tx(s, owners, threshold)
            safe_transaction_response_data = SafeTransactionCreationResponseSerializer(data={
                'signature': {
                    'v': safe_creation.v,
                    'r': safe_creation.r,
                    's': safe_creation.s,
                },
                'safe': safe_creation.safe.address,
                'tx': {
                    'from': safe_creation.deployer,
                    'value': safe_creation.value,
                    'data': safe_creation.data.hex(),
                    'gas': safe_creation.gas,
                    'gas_price': safe_creation.gas_price,
                    'nonce': 0,
                },
                'payment': safe_creation.payment
            })
            assert safe_transaction_response_data.is_valid()
            return Response(status=status.HTTP_201_CREATED, data=safe_transaction_response_data.data)
        else:
            http_status = status.HTTP_422_UNPROCESSABLE_ENTITY \
                if 's' in serializer.errors else status.HTTP_400_BAD_REQUEST
            return Response(status=http_status, data=serializer.errors)


class SafeSignalView(APIView):
    permission_classes = (AllowAny,)

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
            SafeCreation.objects.get(safe=address)
        except SafeCreation.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        fund_deployer_task.delay(address)

        return Response(status=status.HTTP_202_ACCEPTED)


class SafeMultisigTxView(APIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeMultisigTxSerializer

    def post(self, request, address, format=None):
        if not ethereum.utils.check_checksum(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            SafeContract.objects.get(address=address)
        except SafeContract.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        request.data['safe'] = address
        serializer = self.serializer_class(data=request.data)

        if serializer.is_valid():
            data = serializer.validated_data
            safe_multisig_tx = SafeMultisigTx.objects.create_multisig_tx(
                safe=data['safe'],
                to=data['to'],
                value=data['value'],
                data=data['data'],
                operation=data['operation'],
                safe_tx_gas=data['safe_tx_gas'],
                data_gas=data['data_gas'],
                gas_price=data['gas_price'],
                gas_token=data['gas_token'],
                nonce=data['nonce'],
                signatures=data['signatures'],
            )
            data = {'transaction_hash': safe_multisig_tx.tx_hash}
            return Response(status=status.HTTP_200_OK, data=data)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)


class SafeMultisigTxEstimateView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request, address, format=None):
        if not ethereum.utils.check_checksum(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            SafeContract.objects.get(address=address)
        except SafeContract.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        return Response(status=status.HTTP_200_OK)

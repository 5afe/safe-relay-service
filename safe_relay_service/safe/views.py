from django.conf import settings
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from web3 import HTTPProvider, Web3

from safe_relay_service.gas_station.gas_station import GasStation
from safe_relay_service.safe.models import SafeContract, SafeCreation
from safe_relay_service.version import __version__

from .helpers import SafeCreationTxBuilder
from .serializers import (SafeTransactionCreationResultSerializer,
                          SafeTransactionCreationSerializer)

gas_station = GasStation(settings.ETHEREUM_NODE_URL, settings.GAS_STATION_NUMBER_BLOCKS)
w3 = Web3(HTTPProvider(settings.ETHEREUM_NODE_URL))


class AboutView(APIView):
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        content = {
            'name': 'Safe Relay Service',
            'version': __version__,
            'api_version': self.request.version,
            'settings': {
                'ETH_HASH_PREFIX ': settings.ETH_HASH_PREFIX,
                'ETHEREUM_NODE_URL': settings.ETHEREUM_NODE_URL,
                'GAS_STATION_NUMBER_BLOCKS': settings.GAS_STATION_NUMBER_BLOCKS,
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
            if settings.SAFE_GAS_PRICE:
                gas_price = settings.SAFE_GAS_PRICE
            else:
                gas_prices = gas_station.get_gas_prices()
                gas_price = gas_prices.fast

            safe_creation_tx_builder = SafeCreationTxBuilder(w3=w3,
                                                             owners=owners,
                                                             threshold=threshold,
                                                             signature_s=s,
                                                             master_copy=settings.SAFE_PERSONAL_CONTRACT_ADDRESS,
                                                             gas_price=gas_price)

            safe_transaction_data = SafeTransactionCreationResultSerializer(data={
                'signature': {
                    'v': safe_creation_tx_builder.v,
                    'r': safe_creation_tx_builder.r,
                    's': safe_creation_tx_builder.s,
                },
                'safe': safe_creation_tx_builder.safe_address,
                'tx': {
                    'from': safe_creation_tx_builder.deployer_address,
                    'value': safe_creation_tx_builder.contract_creation_tx.value,
                    'data': safe_creation_tx_builder.contract_creation_tx.data.hex(),
                    'gas': safe_creation_tx_builder.gas,
                    'gas_price': safe_creation_tx_builder.gas_price,
                    'nonce': safe_creation_tx_builder.contract_creation_tx.nonce,
                },
                'payment': safe_creation_tx_builder.payment
            })
            assert safe_transaction_data.is_valid()

            safe_contract = SafeContract.objects.create(address=safe_creation_tx_builder.safe_address)
            SafeCreation.objects.create(
                owners=owners,
                threshold=threshold,
                safe=safe_contract,
                deployer=safe_creation_tx_builder.deployer_address,
                signed_tx=safe_creation_tx_builder.raw_tx,
                tx_hash=safe_creation_tx_builder.tx_hash.hex(),
                gas=safe_creation_tx_builder.gas,
                gas_price=gas_price,
                v=safe_creation_tx_builder.v,
                r=safe_creation_tx_builder.r,
                s=safe_creation_tx_builder.s
            )

            return Response(status=status.HTTP_201_CREATED, data=safe_transaction_data.data)
        else:
            # TODO Return 422 if R not valid
            return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)

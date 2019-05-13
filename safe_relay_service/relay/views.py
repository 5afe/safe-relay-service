import logging

from django.conf import settings
from django.db.models import Q

from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg.utils import swagger_auto_schema
from eth_account.account import Account
from rest_framework import filters, status
from rest_framework.generics import CreateAPIView, ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler
from web3 import Web3

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe.exceptions import SafeServiceException
from gnosis.safe.serializers import SafeMultisigEstimateTxSerializer

from safe_relay_service.version import __version__

from .filters import DefaultPagination, SafeMultisigTxFilter
from .models import (EthereumTx, SafeContract, SafeFunding,
                     SafeMultisigTx)
from .serializers import (EthereumTxSerializer,
                          SafeCreationEstimateResponseSerializer,
                          SafeCreationEstimateSerializer,
                          SafeCreationResponseSerializer,
                          SafeCreationSerializer,
                          SafeFundingResponseSerializer,
                          SafeMultisigEstimateTxResponseSerializer,
                          SafeMultisigTxResponseSerializer,
                          SafeRelayMultisigTxSerializer,
                          SafeResponseSerializer)
from .services.safe_creation_service import (SafeCreationServiceException,
                                             SafeCreationServiceProvider)
from .services.transaction_service import (SafeMultisigTxExists,
                                           TransactionServiceException,
                                           TransactionServiceProvider)
from .tasks import fund_deployer_task


logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    # Call REST framework's default exception handler first,
    # to get the standard error response.
    response = exception_handler(exc, context)

    # Now add the HTTP status code to the response.
    if not response:
        if isinstance(exc, (SafeServiceException, SafeCreationServiceException, TransactionServiceException)):
            response = Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            response = Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if str(exc):
            exception_str = '{}: {}'.format(exc.__class__.__name__, exc)
        else:
            exception_str = exc.__class__.__name__
        response.data = {'exception':  exception_str}

        logger.warning('%s - Exception: %s - Data received %s' % (context['request'].build_absolute_uri(),
                                                                  exception_str,
                                                                  context['request'].data))
    return response


class AboutView(APIView):
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        safe_funder_public_key = Account.privateKeyToAccount(settings.SAFE_FUNDER_PRIVATE_KEY).address \
            if settings.SAFE_FUNDER_PRIVATE_KEY else None
        safe_sender_public_key = Account.privateKeyToAccount(settings.SAFE_TX_SENDER_PRIVATE_KEY).address \
            if settings.SAFE_TX_SENDER_PRIVATE_KEY else None
        content = {
            'name': 'Safe Relay Service',
            'version': __version__,
            'api_version': self.request.version,
            'https_detected': self.request.is_secure(),
            'settings': {
                'ETHEREUM_NODE_URL': settings.ETHEREUM_NODE_URL,
                'ETHEREUM_TRACING_NODE_URL': settings.ETHEREUM_TRACING_NODE_URL,
                'ETH_HASH_PREFIX ': settings.ETH_HASH_PREFIX,
                'FIXED_GAS_PRICE': settings.FIXED_GAS_PRICE,
                'GAS_STATION_NUMBER_BLOCKS': settings.GAS_STATION_NUMBER_BLOCKS,
                'NOTIFICATION_SERVICE_PASS': bool(settings.NOTIFICATION_SERVICE_PASS),
                'NOTIFICATION_SERVICE_URI': settings.NOTIFICATION_SERVICE_URI,
                'SAFE_ACCOUNTS_BALANCE_WARNING': settings.SAFE_ACCOUNTS_BALANCE_WARNING,
                'SAFE_CHECK_DEPLOYER_FUNDED_DELAY': settings.SAFE_CHECK_DEPLOYER_FUNDED_DELAY,
                'SAFE_CHECK_DEPLOYER_FUNDED_RETRIES': settings.SAFE_CHECK_DEPLOYER_FUNDED_RETRIES,
                'SAFE_CONTRACT_ADDRESS': settings.SAFE_CONTRACT_ADDRESS,
                'SAFE_FIXED_CREATION_COST': settings.SAFE_FIXED_CREATION_COST,
                'SAFE_FUNDER_MAX_ETH': settings.SAFE_FUNDER_MAX_ETH,
                'SAFE_FUNDER_PUBLIC_KEY': safe_funder_public_key,
                'SAFE_FUNDING_CONFIRMATIONS': settings.SAFE_FUNDING_CONFIRMATIONS,
                'SAFE_OLD_CONTRACT_ADDRESS': settings.SAFE_OLD_CONTRACT_ADDRESS,
                'SAFE_PROXY_FACTORY_ADDRESS': settings.SAFE_PROXY_FACTORY_ADDRESS,
                'SAFE_TX_SENDER_PUBLIC_KEY': safe_sender_public_key,
                'SAFE_VALID_CONTRACT_ADDRESSES': settings.SAFE_VALID_CONTRACT_ADDRESSES,
            }
        }
        return Response(content)


class SafeCreationView(CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeCreationSerializer

    @swagger_auto_schema(responses={201: SafeCreationResponseSerializer(),
                                    400: 'Invalid data',
                                    422: 'Cannot process data'})
    def post(self, request, *args, **kwargs):
        """
        Begins creation of a Safe
        """
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            s, owners, threshold, payment_token = (serializer.data['s'], serializer.data['owners'],
                                                   serializer.data['threshold'], serializer.data['payment_token'])

            safe_creation = SafeCreationServiceProvider().create_safe_tx(s, owners, threshold, payment_token)
            safe_creation_response_data = SafeCreationResponseSerializer(data={
                'signature': {
                    'v': safe_creation.v,
                    'r': safe_creation.r,
                    's': safe_creation.s,
                },
                'tx': {
                    'from': safe_creation.deployer,
                    'value': safe_creation.value,
                    'data': safe_creation.data.hex(),
                    'gas': safe_creation.gas,
                    'gas_price': safe_creation.gas_price,
                    'nonce': 0,
                },
                'tx_hash': safe_creation.tx_hash,
                'payment': safe_creation.payment,
                'payment_token': safe_creation.payment_token or NULL_ADDRESS,
                'safe': safe_creation.safe.address,
                'deployer': safe_creation.deployer,
                'funder': safe_creation.funder,
            })
            safe_creation_response_data.is_valid(raise_exception=True)
            return Response(status=status.HTTP_201_CREATED, data=safe_creation_response_data.data)
        else:
            http_status = status.HTTP_422_UNPROCESSABLE_ENTITY \
                if 's' in serializer.errors else status.HTTP_400_BAD_REQUEST
            return Response(status=http_status, data=serializer.errors)


class SafeCreationEstimateView(CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeCreationEstimateSerializer

    @swagger_auto_schema(responses={201: SafeCreationEstimateResponseSerializer(),
                                    400: 'Invalid data',
                                    422: 'Cannot process data'})
    def post(self, request, *args, **kwargs):
        """
        Estimates creation of a Safe
        """
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            number_owners, payment_token = serializer.data['number_owners'], serializer.data['payment_token']
            safe_creation_estimate = SafeCreationServiceProvider().estimate_safe_creation(number_owners, payment_token)
            safe_creation_estimate_response_data = SafeCreationEstimateResponseSerializer(safe_creation_estimate)
            return Response(status=status.HTTP_200_OK, data=safe_creation_estimate_response_data.data)
        else:
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data=serializer.errors)


class SafeView(APIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeResponseSerializer

    @swagger_auto_schema(responses={200: SafeResponseSerializer(),
                                    404: 'Safe not found',
                                    422: 'Safe address checksum not valid'})
    def get(self, request, address, format=None):
        """
        Get status of the safe
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeContract.objects.get(address=address)
            except SafeContract.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            safe_info = SafeCreationServiceProvider().retrieve_safe_info(address)
            serializer = self.serializer_class(safe_info)
            return Response(status=status.HTTP_200_OK, data=serializer.data)


class SafeSignalView(APIView):
    permission_classes = (AllowAny,)

    @swagger_auto_schema(responses={200: SafeFundingResponseSerializer(),
                                    404: 'Safe not found',
                                    422: 'Safe address checksum not valid'})
    def get(self, request, address, format=None):
        """
        Get status of the safe creation
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                safe_funding = SafeFunding.objects.get(safe=address)
                serializer = SafeFundingResponseSerializer(safe_funding)
                return Response(status=status.HTTP_200_OK, data=serializer.data)
            except SafeFunding.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

    @swagger_auto_schema(responses={202: 'Task was queued',
                                    404: 'Safe not found',
                                    422: 'Safe address checksum not valid'})
    def put(self, request, address, format=None):
        """
        Force check of a safe balance to start the safe creation
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeContract.objects.get(address=address)
            except SafeContract.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            fund_deployer_task.delay(address)
            return Response(status=status.HTTP_202_ACCEPTED)


class SafeMultisigTxEstimateView(CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeMultisigEstimateTxSerializer

    @swagger_auto_schema(responses={200: SafeMultisigEstimateTxResponseSerializer(),
                                    400: 'Data not valid',
                                    404: 'Safe not found',
                                    422: 'Safe address checksum not valid/Tx not valid'})
    def post(self, request, address):
        """
        Estimates a Safe Multisig Transaction. `operational_gas` and `data_gas` are deprecated, use `base_gas` instead
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeContract.objects.get(address=address)
            except SafeContract.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

        request.data['safe'] = address
        serializer = self.get_serializer_class()(data=request.data)

        if serializer.is_valid():
            data = serializer.validated_data

            transaction_estimation = TransactionServiceProvider().estimate_tx(address, data['to'], data['value'],
                                                                              data['data'], data['operation'],
                                                                              data['gas_token'])
            response_serializer = SafeMultisigEstimateTxResponseSerializer(transaction_estimation)
            return Response(status=status.HTTP_200_OK, data=response_serializer.data)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)


class SafeMultisigTxView(ListAPIView):
    permission_classes = (AllowAny,)
    pagination_class = DefaultPagination
    filter_backends = (DjangoFilterBackend, filters.OrderingFilter)
    filterset_class = SafeMultisigTxFilter
    ordering_fields = '__all__'
    ordering = ('-created',)

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return SafeMultisigTxResponseSerializer
        elif self.request.method == 'POST':
            return SafeRelayMultisigTxSerializer

    def get_queryset(self):
        return SafeMultisigTx.objects.filter(safe=self.kwargs['address'])

    @swagger_auto_schema(responses={400: 'Data not valid',
                                    404: 'Safe not found/No txs for that Safe',
                                    422: 'Safe address checksum not valid/Tx not valid'})
    def get(self, request, address):
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeContract.objects.get(address=address)
            except SafeContract.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

        response = super().get(request, address)
        if response.data['count'] == 0:
            response.status_code = status.HTTP_404_NOT_FOUND
        return response

    @swagger_auto_schema(responses={201: SafeMultisigTxResponseSerializer(),
                                    400: 'Data not valid',
                                    404: 'Safe not found',
                                    422: 'Safe address checksum not valid/Tx not valid'})
    def post(self, request, address, format=None):
        """
        Send a Safe Multisig Transaction
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeContract.objects.get(address=address)
            except SafeContract.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            request.data['safe'] = address
            serializer = self.get_serializer_class()(data=request.data)

            if not serializer.is_valid():
                return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)
            else:
                data = serializer.validated_data

                try:
                    safe_multisig_tx = TransactionServiceProvider().create_multisig_tx(
                        safe_address=data['safe'],
                        to=data['to'],
                        value=data['value'],
                        data=data['data'],
                        operation=data['operation'],
                        safe_tx_gas=data['safe_tx_gas'],
                        base_gas=data['data_gas'],
                        gas_price=data['gas_price'],
                        gas_token=data['gas_token'],
                        nonce=data['nonce'],
                        refund_receiver=data['refund_receiver'],
                        signatures=data['signatures']
                    )
                    response_serializer = SafeMultisigTxResponseSerializer(safe_multisig_tx)
                    return Response(status=status.HTTP_201_CREATED, data=response_serializer.data)
                except SafeMultisigTxExists:
                    return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    data='Safe Multisig Tx with that nonce already exists')


class EthereumTxView(ListAPIView):
    permission_classes = (AllowAny,)
    pagination_class = DefaultPagination
    filter_backends = (DjangoFilterBackend, filters.OrderingFilter)
    ordering_fields = '__all__'
    ordering = ('-block_number',)
    serializer_class = EthereumTxSerializer

    def get_queryset(self):
        address = self.kwargs['address']
        return EthereumTx.objects.filter(Q(to=address) |
                                         Q(_from=address) |
                                         Q(internal_txs__to=address) |
                                         Q(internal_txs___from=address) |
                                         Q(internal_txs__contract_address=address)
                                         ).distinct().prefetch_related('internal_txs')

    @swagger_auto_schema(responses={400: 'Data not valid',
                                    404: 'Safe not found/No txs for that Safe',
                                    422: 'Safe address checksum not valid/Tx not valid'})
    def get(self, request, address):
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeContract.objects.get(address=address)
            except SafeContract.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

        response = super().get(request, address)
        if response.data['count'] == 0:
            response.status_code = status.HTTP_404_NOT_FOUND
        return response

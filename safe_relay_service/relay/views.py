import ethereum.utils
from django.conf import settings
from drf_yasg.utils import swagger_auto_schema
from gnosis.safe.safe_service import SafeServiceException, SafeServiceProvider
from gnosis.safe.serializers import SafeMultisigEstimateTxSerializer
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler

from django_eth.constants import NULL_ADDRESS
from safe_relay_service.gas_station.gas_station import GasStationProvider
from safe_relay_service.relay.models import (SafeContract, SafeCreation,
                                             SafeFunding, SafeMultisigTx)
from safe_relay_service.relay.tasks import fund_deployer_task
from safe_relay_service.tokens.models import Token
from safe_relay_service.version import __version__

from .serializers import (SafeCreationSerializer,
                          SafeFundingResponseSerializer,
                          SafeMultisigEstimateTxResponseSerializer,
                          SafeMultisigTxResponseSerializer,
                          SafeRelayMultisigTxSerializer,
                          SafeResponseSerializer,
                          SafeTransactionCreationResponseSerializer)


def custom_exception_handler(exc, context):
    # Call REST framework's default exception handler first,
    # to get the standard error response.
    response = exception_handler(exc, context)

    # Now add the HTTP status code to the response.
    if not response:
        if isinstance(exc, SafeServiceException):
            response = Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            response = Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        if str(exc):
            exception_str = '{}: {}'.format(exc.__class__.__name__, exc)
        else:
            exception_str = exc.__class__.__name__
        response.data = {'exception':  exception_str}

    return response


class AboutView(APIView):
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        if settings.SAFE_FUNDER_PRIVATE_KEY:
            safe_funder_public_key = ethereum.utils.checksum_encode(ethereum.utils.privtoaddr(
                settings.SAFE_FUNDER_PRIVATE_KEY))
        else:
            safe_funder_public_key = None
        if settings.SAFE_TX_SENDER_PRIVATE_KEY:
            safe_sender_public_key = ethereum.utils.checksum_encode(ethereum.utils.privtoaddr(
                settings.SAFE_TX_SENDER_PRIVATE_KEY))
        else:
            safe_sender_public_key = None
        content = {
            'name': 'Safe Relay Service',
            'version': __version__,
            'api_version': self.request.version,
            'https_detected': self.request.is_secure(),
            'settings': {
                'ETHEREUM_NODE_URL': settings.ETHEREUM_NODE_URL,
                'ETH_HASH_PREFIX ': settings.ETH_HASH_PREFIX,
                'GAS_STATION_NUMBER_BLOCKS': settings.GAS_STATION_NUMBER_BLOCKS,
                'SAFE_CHECK_DEPLOYER_FUNDED_DELAY': settings.SAFE_CHECK_DEPLOYER_FUNDED_DELAY,
                'SAFE_CHECK_DEPLOYER_FUNDED_RETRIES': settings.SAFE_CHECK_DEPLOYER_FUNDED_RETRIES,
                'SAFE_FUNDER_MAX_ETH': settings.SAFE_FUNDER_MAX_ETH,
                'SAFE_FUNDER_PUBLIC_KEY': safe_funder_public_key,
                'SAFE_FUNDING_CONFIRMATIONS': settings.SAFE_FUNDING_CONFIRMATIONS,
                'SAFE_GAS_PRICE': settings.SAFE_GAS_PRICE,
                'SAFE_CONTRACT_ADDRESS': settings.SAFE_CONTRACT_ADDRESS,
                'SAFE_TX_SENDER_PUBLIC_KEY': safe_sender_public_key,
            }
        }
        return Response(content)


class SafeCreationView(CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeCreationSerializer

    @swagger_auto_schema(responses={201: SafeTransactionCreationResponseSerializer(),
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
            safe_creation = SafeCreation.objects.create_safe_tx(s, owners, threshold, payment_token)
            payment_token = safe_creation.payment_token or NULL_ADDRESS

            # FIXME Refactor token payment calculation
            payment = safe_creation.payment
            if payment_token != NULL_ADDRESS:
                try:
                    price_margin = 1 + 1 / 100  # TODO Make it configurable
                    gas_token_model = Token.objects.get(address=payment_token)
                    payment = gas_token_model.calculate_gas_price(payment, price_margin=price_margin)
                except Token.DoesNotExist:
                    return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Gas token not valid')

            safe_transaction_response_data = SafeTransactionCreationResponseSerializer(data={
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
                'payment': payment,
                'payment_token': payment_token,
                'safe': safe_creation.safe.address,
                'deployer': safe_creation.deployer
            })
            safe_transaction_response_data.is_valid(raise_exception=True)
            return Response(status=status.HTTP_201_CREATED, data=safe_transaction_response_data.data)
        else:
            http_status = status.HTTP_422_UNPROCESSABLE_ENTITY \
                if 's' in serializer.errors else status.HTTP_400_BAD_REQUEST
            return Response(status=http_status, data=serializer.errors)


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
        if not ethereum.utils.check_checksum(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeContract.objects.get(address=address)
            except SafeContract.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            safe_service = SafeServiceProvider()
            nonce = safe_service.retrieve_nonce(address)
            threshold = safe_service.retrieve_threshold(address)
            owners = safe_service.retrieve_owners(address)
            serializer = self.serializer_class(data={
                'address': address,
                'nonce': nonce,
                'threshold': threshold,
                'owners': owners,
            })
            assert serializer.is_valid(), serializer.errors
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
        if not ethereum.utils.check_checksum(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                safe_funding = SafeFunding.objects.get(safe=address)
            except SafeFunding.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            serializer = SafeFundingResponseSerializer(safe_funding)
            return Response(status=status.HTTP_200_OK, data=serializer.data)

    @swagger_auto_schema(responses={202: 'Task was queued',
                                    404: 'Safe not found',
                                    422: 'Safe address checksum not valid'})
    def put(self, request, address, format=None):
        """
        Force check of a safe balance to start the safe creation
        """
        if not ethereum.utils.check_checksum(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeCreation.objects.get(safe=address)
            except SafeCreation.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            fund_deployer_task.delay(address)
            return Response(status=status.HTTP_202_ACCEPTED)


class SafeMultisigTxView(CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeRelayMultisigTxSerializer

    @swagger_auto_schema(responses={201: SafeMultisigTxResponseSerializer(),
                                    400: 'Data not valid',
                                    404: 'Safe not found',
                                    422: 'Safe address checksum not valid/Tx not valid'})
    def post(self, request, address, format=None):
        """
        Send a Safe Multisig Transaction
        """
        if not ethereum.utils.check_checksum(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeContract.objects.get(address=address)
            except SafeContract.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            request.data['safe'] = address
            serializer = self.serializer_class(data=request.data)

            if not serializer.is_valid():
                return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)
            else:
                data = serializer.validated_data

                # If gas_token is specified, we see if the gas_price matches the current token value and use as the
                # external tx gas the fast gas price from the gas station.
                # If not, we just use the internal tx gas_price for the gas_price
                gas_token = data['gas_token'] or NULL_ADDRESS
                gas_price = data['gas_price']
                current_gas_price = GasStationProvider().get_gas_prices().fast
                if gas_token != NULL_ADDRESS:
                    try:
                        gas_token_model = Token.objects.get(address=gas_token)
                        estimated_gas_price = gas_token_model.calculate_gas_price(current_gas_price)
                        if gas_price < estimated_gas_price:
                            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                            data='Required gas-price>=%d to use gas-token' % estimated_gas_price)
                        # We use gas station tx gas price. We cannot use internal tx's because is calculated
                        # based on the gas token
                        tx_gas_price = current_gas_price
                    except Token.DoesNotExist:
                        return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Gas token not valid')
                else:
                    if gas_price < current_gas_price:
                        return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                        data='Required gas-price>=%d' % current_gas_price)
                    # We use internal tx gas price
                    tx_gas_price = gas_price

                try:
                    safe_multisig_tx = SafeMultisigTx.objects.create_multisig_tx(
                        safe_address=data['safe'],
                        to=data['to'],
                        value=data['value'],
                        data=data['data'],
                        operation=data['operation'],
                        safe_tx_gas=data['safe_tx_gas'],
                        data_gas=data['data_gas'],
                        gas_price=data['gas_price'],
                        gas_token=data['gas_token'],
                        nonce=data['nonce'],
                        refund_receiver=data['refund_receiver'],
                        signatures=data['signatures'],
                        tx_gas_price=tx_gas_price
                    )
                    response_serializer = SafeMultisigTxResponseSerializer(data={'transaction_hash':
                                                                                 safe_multisig_tx.tx_hash})
                    assert response_serializer.is_valid(), response_serializer.errors
                    return Response(status=status.HTTP_201_CREATED, data=response_serializer.data)
                except SafeMultisigTx.objects.SafeMultisigTxExists:
                    return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    data='Safe Multisig Tx with that nonce already exists')
                except SafeMultisigTx.objects.SafeMultisigTxError as exc:
                    return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    data='Error procesing tx: ' + str(exc))


class SafeMultisigTxEstimateView(CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeMultisigEstimateTxSerializer

    @swagger_auto_schema(responses={200: SafeMultisigEstimateTxResponseSerializer(),
                                    400: 'Data not valid',
                                    404: 'Safe not found',
                                    422: 'Safe address checksum not valid/Tx not valid'})
    def post(self, request, address, format=None):
        """
        Estimates a Safe Multisig Transaction
        """
        if not ethereum.utils.check_checksum(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            SafeContract.objects.get(address=address)
        except SafeContract.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        request.data['safe'] = address
        serializer = self.serializer_class(data=request.data)

        if serializer.is_valid():
            safe_service = SafeServiceProvider()
            data = serializer.validated_data
            gas_token = data['gas_token'] or NULL_ADDRESS
            if gas_token != NULL_ADDRESS:
                try:
                    gas_token_model = Token.objects.get(address=gas_token)
                except Token.DoesNotExist:
                    return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Gas token not valid')
            else:
                gas_token_model = None

            last_used_nonce = SafeMultisigTx.objects.get_last_nonce_for_safe(address)
            safe_tx_gas = safe_service.estimate_tx_gas(address, data['to'], data['value'], data['data'],
                                                       data['operation'])
            safe_data_tx_gas = safe_service.estimate_tx_data_gas(address, data['to'], data['value'], data['data'],
                                                                 data['operation'], gas_token, safe_tx_gas)
            safe_operational_tx_gas = safe_service.estimate_tx_operational_gas(address,
                                                                               len(data['data']) if data['data'] else 0)
            gas_price = GasStationProvider().get_gas_prices().fast

            if gas_token_model:
                price_margin = 1 + 1 / 100  # TODO Make it configurable
                # Gas price needs to be adjusted for the token
                gas_price = gas_token_model.calculate_gas_price(gas_price, price_margin=price_margin)

            response_data = {'safe_tx_gas': safe_tx_gas,
                             'data_gas': safe_data_tx_gas,
                             'operational_gas': safe_operational_tx_gas,
                             'gas_price': gas_price,
                             'gas_token': gas_token,
                             'last_used_nonce': last_used_nonce}
            response_serializer = SafeMultisigEstimateTxResponseSerializer(data=response_data)
            assert response_serializer.is_valid(), response_serializer.errors
            return Response(status=status.HTTP_200_OK, data=response_serializer.data)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)

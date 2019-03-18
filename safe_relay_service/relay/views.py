from django.conf import settings
from django.core import serializers
from django_eth.constants import NULL_ADDRESS
from django.db import connection
from drf_yasg.utils import swagger_auto_schema
from eth_account.account import Account
from gnosis.safe.safe_service import SafeServiceException, SubscriptionStatuses
from gnosis.safe.serializers import (SafeMultisigEstimateTxSerializer)

from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler
from web3 import Web3
from datetime import datetime

from safe_relay_service.relay.models import (SafeContract, SafeCreation,
                                             SafeFunding, SafeMultisigTx, SafeMultisigSubTx)
from safe_relay_service.relay.tasks import fund_deployer_task
from safe_relay_service.tokens.models import Token
from safe_relay_service.version import __version__
from hexbytes import HexBytes

from .relay_service import RelayServiceException, RelayServiceProvider
from .serializers import (SafeCreationSerializer,
                          SafeFundingResponseSerializer,
                          SafeMultisigEstimateTxResponseSerializer,
                          SafeMultisigTxResponseSerializer,
                          SafeMultisigSubTxResponseSerializer,
                          SafeMultisigSubTxExecuteResponseSerializer,
                          SafeRelayMultisigTxSerializer,
                          SafeRelayMultisigSubTxSerializer,
                          SafeRelayMultisigSubTxExecuteSerializer,
                          SafeResponseSerializer,
                          SafeLookupResponseSerializer,
                          SafeTransactionCreationResponseSerializer,
                          TxListSerializer)


def custom_exception_handler(exc, context):
    # Call REST framework's default exception handler first,
    # to get the standard error response.
    response = exception_handler(exc, context)

    # Now add the HTTP status code to the response.
    if not response:
        if isinstance(exc, (SafeServiceException, RelayServiceException)):
            response = Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            response = Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        if str(exc):
            exception_str = '{}: {}'.format(exc.__class__.__name__, exc)
        else:
            exception_str = exc.__class__.__name__
        response.data = {'exception': exception_str}

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
                'ETH_HASH_PREFIX ': settings.ETH_HASH_PREFIX,
                'GAS_STATION_NUMBER_BLOCKS': settings.GAS_STATION_NUMBER_BLOCKS,
                'NOTIFICATION_SERVICE_URI': settings.NOTIFICATION_SERVICE_URI,
                'SAFE_CHECK_DEPLOYER_FUNDED_DELAY': settings.SAFE_CHECK_DEPLOYER_FUNDED_DELAY,
                'SAFE_CHECK_DEPLOYER_FUNDED_RETRIES': settings.SAFE_CHECK_DEPLOYER_FUNDED_RETRIES,
                'SAFE_FIXED_CREATION_COST': settings.SAFE_FIXED_CREATION_COST,
                'SAFE_FUNDER_MAX_ETH': settings.SAFE_FUNDER_MAX_ETH,
                'SAFE_FUNDER_PUBLIC_KEY': safe_funder_public_key,
                'SAFE_FUNDING_CONFIRMATIONS': settings.SAFE_FUNDING_CONFIRMATIONS,
                'SAFE_GAS_PRICE': settings.SAFE_GAS_PRICE,
                'SAFE_CONTRACT_ADDRESS': settings.SAFE_CONTRACT_ADDRESS,
                'SAFE_VALID_CONTRACT_ADDRESSES': settings.SAFE_VALID_CONTRACT_ADDRESSES,
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
            s, owners, threshold, payment_token, wallet_type = (serializer.data['s'],
                                                                serializer.data['owners'],
                                                                serializer.data['threshold'],
                                                                serializer.data['payment_token'],
                                                                serializer.data['wallet_type'])

            if payment_token and payment_token != NULL_ADDRESS:
                try:
                    token = Token.objects.get(address=payment_token, gas=True)
                    payment_token_eth_value = token.get_eth_value()
                except Token.DoesNotExist:
                    return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Gas token not valid')
            else:
                payment_token_eth_value = 1.0

            safe_creation = SafeCreation.objects.create_safe_tx(wallet_type, s, owners, threshold, payment_token,
                                                                payment_token_eth_value=payment_token_eth_value,
                                                                fixed_creation_cost=settings.SAFE_FIXED_CREATION_COST)
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
                'payment': safe_creation.payment,
                'payment_token': safe_creation.payment_token or NULL_ADDRESS,
                'safe': safe_creation.safe.address,
                'subscription_module': safe_creation.safe.subscription_module_address,
                'deployer': safe_creation.deployer,
                'funder': safe_creation.funder,
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
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeFunding.objects.get(safe=address, safe_deployed=True)
            except SafeFunding.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            relay_service = RelayServiceProvider()
            nonce = relay_service.retrieve_nonce(address)
            threshold = relay_service.retrieve_threshold(address)
            owners = relay_service.retrieve_owners(address)
            master_copy = relay_service.retrieve_master_copy_address(address)
            serializer = self.serializer_class(data={
                'address': address,
                'master_copy': master_copy,
                'nonce': nonce,
                'threshold': threshold,
                'owners': owners,
            })
            assert serializer.is_valid(), serializer.errors
            return Response(status=status.HTTP_200_OK, data=serializer.data)


class TxListView(APIView):
    permission_classes = (AllowAny,)
    serializer_class = TxListSerializer

    @swagger_auto_schema(responses={200: TxListSerializer(),
                                    404: 'No transactions found',
                                    422: 'Safe address checksum not valid'})
    def get(self, request, address, flag, format=None):
        """
        Get all active subscriptions or all transactions for a safe
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                if flag == 'active':
                    subscriptions = SafeMultisigSubTx.objects.all().filter(safe_id=address, status__in=[0, 1, 2])
                    transactions = []
                elif flag == 'all':
                    subscriptions = SafeMultisigSubTx.objects.all().filter(safe_id=address)
                    transactions = SafeMultisigTx.objects.all().filter(safe_id=address)

            except SafeMultisigSubTx.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            data = {
                'subscriptions': {},
                'transactions': []
            }
            for sub in subscriptions:
                subscription = {
                    'created': sub.created,
                    'to': sub.to,
                    'value': sub.value,
                    'data': HexBytes(sub.data) if sub.data else '0x',
                    'period': sub.period,
                    'start_date': sub.start_date,
                    'end_date': sub.end_date,
                    'unique': sub.uniq_id
                }
                if sub.status == 1 and flag == 'active':
                    time_stamp = datetime.now().timestamp()
                    if time_stamp < sub.start_date:
                        data['subscriptions'][subscription['to']] = subscription
                else:
                    data['subscriptions'][subscription['to']] = subscription

            for trans in transactions:
                transaction = {
                    'created': trans.created,
                    'to': trans.to,
                    'value': trans.value
                }
                data['transactions'].append(transaction)

            serializer = self.serializer_class(data=data)
            assert serializer.is_valid(), serializer.errors
            return Response(status=status.HTTP_200_OK, data=serializer.data)


class SafeLookupView(APIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeLookupResponseSerializer

    @swagger_auto_schema(responses={200: SafeLookupResponseSerializer(),
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
                with connection.cursor() as cursor:
                    cursor.execute(
                        "select address, subscription_module_address from relay_safecontract where address in (select safe_id from relay_safecreation where owners::varchar like '%%" + address + "%%')")
                    safe_data = cursor.fetchall()
            except SafeCreation.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            # relay_service = RelayServiceProvider()
            # owners = relay_service.retrieve_owners(address)
            # master_copy = relay_service.retrieve_master_copy_address(address)
            # threshold = relay_service.retrieve_threshold(address)
            # serializer = self.serializer_class(data={
            #     'address': safe_data['address'],
            #     'sub_module_address': safe_data['sub_module_address'],
            #     'master_copy': master_copy,
            #     'threshold': threshold,
            #     'owners': owners,
            # })
            # assert serializer.is_valid(), serializer.errors
            # return Response(status=status.HTTP_200_OK, data=serializer.data)
            if (len(safe_data) > 0):
                response = {
                    "safe_address": safe_data[0][0],
                    "subscription_module_address": safe_data[0][1]
                }
                # assert serializer.is_valid(), serializer.errors
                return Response(status=status.HTTP_200_OK, data=response)
            else:
                return Response(status=status.HTTP_400_BAD_REQUEST)


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
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeCreation.objects.get(safe=address)
            except SafeCreation.DoesNotExist:
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
    def post(self, request, address, format=None):
        """
        Estimates a Safe Multisig Transaction
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            SafeContract.objects.get(address=address)
        except SafeContract.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        request.data['safe'] = address
        serializer = self.serializer_class(data=request.data)

        if serializer.is_valid():
            relay_service = RelayServiceProvider()
            data = serializer.validated_data

            last_used_nonce = SafeMultisigTx.objects.get_last_nonce_for_safe(address)
            safe_tx_gas = relay_service.estimate_tx_gas(address, data['to'], data['value'], data['data'],
                                                        data['operation'])
            safe_data_tx_gas = relay_service.estimate_tx_data_gas(address, data['to'], data['value'], data['data'],
                                                                  data['operation'], data['gas_token'], safe_tx_gas)
            safe_operational_tx_gas = relay_service.estimate_tx_operational_gas(address,
                                                                                len(data['data'])
                                                                                if data['data'] else 0)
            try:
                gas_price = relay_service.estimate_tx_gas_price(data['gas_token'])
            except RelayServiceException as e:
                return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data=str(e))

            response_data = {'safe_tx_gas': safe_tx_gas,
                             'data_gas': safe_data_tx_gas,
                             'operational_gas': safe_operational_tx_gas,
                             'gas_price': gas_price,
                             'gas_token': data['gas_token'] or NULL_ADDRESS,
                             'last_used_nonce': last_used_nonce}
            response_serializer = SafeMultisigEstimateTxResponseSerializer(data=response_data)
            assert response_serializer.is_valid(), response_serializer.errors
            return Response(status=status.HTTP_200_OK, data=response_serializer.data)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)


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
        if not Web3.isChecksumAddress(address):
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
                        signatures=data['signatures']
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


class SafeMultisigSubTxView(CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeRelayMultisigSubTxSerializer

    @swagger_auto_schema(responses={201: SafeMultisigSubTxResponseSerializer(),
                                    400: 'Data not valid',
                                    404: 'Safe not found',
                                    422: 'Safe address checksum not valid/Tx not valid'})
    def post(self, request, format=None):
        """
        Send a Safe Multisig Transaction
        """
        if not Web3.isChecksumAddress(request.data['sub_module_address']):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                safe_contract = SafeContract.objects.get(subscription_module_address=request.data['sub_module_address'])
            except SafeContract.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            serializer = self.serializer_class(data=request.data)

            if not serializer.is_valid():
                return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)
            else:
                data = serializer.validated_data

                try:
                    safe_multisig_subtx = SafeMultisigSubTx.objects.create_multisig_subtx(
                        safe_address=safe_contract,
                        sub_module_address=safe_contract.subscription_module_address,
                        to=data['to'],
                        value=data['value'],
                        data=data['data'],
                        period=data['period'],
                        start_date=data['start_date'],
                        end_date=data['end_date'],
                        uniq_id=data['uniq_id'],
                        signatures=data['signatures']
                    )
                    response_serializer = SafeMultisigSubTxResponseSerializer(
                        data={'sub_tx_id': safe_multisig_subtx.id}
                    )
                    assert response_serializer.is_valid(), response_serializer.errors
                    return Response(status=status.HTTP_201_CREATED, data=response_serializer.data)

                except SafeMultisigTx.objects.SafeMultisigTxExists:
                    return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    data='Safe Multisig Tx with that nonce already exists')
                except SafeMultisigTx.objects.SafeMultisigTxError as exc:
                    return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    data='Error procesing tx: ' + str(exc))


class SafeMultisigSubTxExecute(CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeRelayMultisigSubTxExecuteSerializer

    @swagger_auto_schema(responses={201: SafeMultisigSubTxResponseSerializer(),
                                    400: 'Data not valid',
                                    404: 'Safe not found',
                                    422: 'Safe address checksum not valid/Tx not valid'})
    def post(self, request, format=None):
        """
        Send a Safe Multisig Transaction
        """

        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)
        else:
            data = serializer.validated_data

            try:
                execute_ids = data['execute_ids']

                sub_subscriptions_to_exec = SafeMultisigSubTx.objects.all().filter(
                    id__in=execute_ids
                ).select_related('safe')

                relay_service = RelayServiceProvider()

                (processed_subscriptions, skipped_subscriptions) = relay_service.send_multisig_subtx(
                    sub_subscriptions_to_exec
                )

                response_serializer = SafeMultisigSubTxExecuteResponseSerializer(
                    data={'processed': processed_subscriptions, 'skipped': skipped_subscriptions}
                )

                assert response_serializer.is_valid(), response_serializer.errors

                # TODO: add a seperate table that tracks txn hashes of subscriptions.
                return Response(status=status.HTTP_201_CREATED, data=response_serializer.data)

            except SafeMultisigTx.objects.SafeMultisigTxExists:
                return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                data='Safe Multisig Tx with that nonce already exists')
            except SafeMultisigTx.objects.SafeMultisigTxError as exc:
                return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                data='Error procesing tx: ' + str(exc))

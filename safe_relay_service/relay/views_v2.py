from logging import getLogger

from drf_yasg.utils import swagger_auto_schema
from hexbytes import HexBytes
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from web3 import Web3

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe.serializers import SafeMultisigEstimateTxSerializer

from safe_relay_service.relay.services import TransactionServiceProvider

from .models import SafeCreation2
from .serializers import (
    SafeCreation2ResponseSerializer,
    SafeCreation2Serializer,
    SafeCreationEstimateResponseSerializer,
    SafeCreationEstimateV2Serializer,
    SafeFunding2ResponseSerializer,
    SafeMultisigEstimateTxResponseV2Serializer,
)
from .services.safe_creation_service import SafeCreationV1_0_0ServiceProvider
from .tasks import (
    begin_circles_onboarding_task,
    begin_circles_onboarding_organization_task,
)

logger = getLogger(__name__)


class SafeCreationEstimateView(CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeCreationEstimateV2Serializer

    @swagger_auto_schema(
        deprecated=True,
        operation_description="Use /v3/safes/estimates/",
        responses={
            201: SafeCreationEstimateResponseSerializer(),
            400: "Invalid data",
            422: "Cannot process data",
        },
    )
    def post(self, request, *args, **kwargs):
        """
        Estimates creation of a Safe
        """
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            number_owners = serializer.data["number_owners"]
            safe_creation_estimates = SafeCreationV1_0_0ServiceProvider().estimate_safe_creation_for_all_tokens(
                number_owners
            )
            safe_creation_estimate_response_data = (
                SafeCreationEstimateResponseSerializer(
                    safe_creation_estimates, many=True
                )
            )
            return Response(
                status=status.HTTP_200_OK,
                data=safe_creation_estimate_response_data.data,
            )
        else:
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY, data=serializer.errors
            )


class SafeCreationView(CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeCreation2Serializer

    @swagger_auto_schema(
        deprecated=True,
        operation_description="Use /v3/safes/",
        responses={
            201: SafeCreation2ResponseSerializer(),
            400: "Invalid data",
            422: "Cannot process data",
        },
    )
    def post(self, request, *args, **kwargs):
        """
        Begins creation of a Gnosis Safe V1.0.0
        """
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            salt_nonce, owners, threshold, payment_token = (
                serializer.data["salt_nonce"],
                serializer.data["owners"],
                serializer.data["threshold"],
                serializer.data["payment_token"],
            )

            safe_creation_service = SafeCreationV1_0_0ServiceProvider()
            safe_creation = safe_creation_service.create2_safe_tx(
                salt_nonce, owners, threshold, payment_token
            )
            safe_creation_response_data = SafeCreation2ResponseSerializer(
                data={
                    "safe": safe_creation.safe.address,
                    "master_copy": safe_creation.master_copy,
                    "proxy_factory": safe_creation.proxy_factory,
                    "payment": safe_creation.payment,
                    "payment_token": safe_creation.payment_token or NULL_ADDRESS,
                    "payment_receiver": safe_creation.payment_receiver or NULL_ADDRESS,
                    "setup_data": HexBytes(safe_creation.setup_data).hex(),
                    "gas_estimated": safe_creation.gas_estimated,
                    "gas_price_estimated": safe_creation.gas_price_estimated,
                }
            )
            safe_creation_response_data.is_valid(raise_exception=True)
            return Response(
                status=status.HTTP_201_CREATED, data=safe_creation_response_data.data
            )
        else:
            logger.error("Error in SafeCreationView")
            logger.error(serializer.errors)
            logger.error("Request data:")
            logger.error(request.data)
            logger.error(request.body)
            logger.error(request.META["HTTP_HOST"])
            logger.error(request.META["HTTP_USER_AGENT"])
            logger.error(request.META["HTTP_CONNECTION"])
            logger.error(request.META["REMOTE_ADDR"])
            logger.error(request.META["RAW_URI"])
            logger.error(request.META["QUERY_STRING"])

            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY, data=serializer.errors
            )


class SafeMultisigTxEstimateView(CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeMultisigEstimateTxSerializer
    serializer_response_class = SafeMultisigEstimateTxResponseV2Serializer

    @swagger_auto_schema(
        responses={
            200: serializer_response_class(),
            400: "Data not valid",
            404: "Safe not found",
            422: "Safe address checksum not valid/Tx not valid",
        }
    )
    def post(self, request, address):
        """
        Estimates a Safe Multisig Transaction. `operational_gas` and `data_gas` are deprecated, use `base_gas` instead
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        request.data["safe"] = address
        serializer = self.get_serializer_class()(data=request.data)

        if serializer.is_valid():
            data = serializer.validated_data

            transaction_estimation = TransactionServiceProvider().estimate_tx(
                address,
                data["to"],
                data["value"],
                data["data"],
                data["operation"],
                data["gas_token"],
            )
            response_serializer = self.serializer_response_class(transaction_estimation)
            return Response(status=status.HTTP_200_OK, data=response_serializer.data)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)


class SafeSignalView(APIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeFunding2ResponseSerializer

    @swagger_auto_schema(
        responses={
            200: SafeFunding2ResponseSerializer(),
            404: "Safe not found",
            422: "Safe address checksum not valid",
        }
    )
    def get(self, request, address, format=None):
        """
        Get status of the safe creation
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                safe_creation2 = SafeCreation2.objects.get(safe=address)
                serializer = self.serializer_class(safe_creation2)
                return Response(status=status.HTTP_200_OK, data=serializer.data)
            except SafeCreation2.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

    @swagger_auto_schema(
        responses={
            202: "Task was queued",
            404: "Safe not found",
            422: "Safe address checksum not valid",
        }
    )
    def put(self, request, address, format=None):
        """
        Force check of a safe balance to start the safe creation
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeCreation2.objects.get(safe=address)
            except SafeCreation2.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            # Manually start custom Circles onboarding task
            begin_circles_onboarding_task.delay(address)
            return Response(status=status.HTTP_202_ACCEPTED)


class OrganizationSignalView(APIView):
    permission_classes = (AllowAny,)
    serializer_class = SafeFunding2ResponseSerializer

    @swagger_auto_schema(
        responses={
            202: "Task was queued",
            404: "Safe not found",
            422: "Safe address checksum not valid",
        }
    )
    def put(self, request, address, format=None):
        """
        Force check of a safe balance to start the safe creation for a Circles
        organization
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            safe_creation = None
            try:
                safe_creation = SafeCreation2.objects.get(safe=address)
            except SafeCreation2.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            # Manually start custom Circles organization onboarding task
            begin_circles_onboarding_organization_task.delay(
                address, safe_creation.owners[0]
            )
            return Response(status=status.HTTP_202_ACCEPTED)

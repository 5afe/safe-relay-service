import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.generics import ListAPIView
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from .gas_station import GasStationProvider
from .models import GasPrice
from .serializers import GasPriceSerializer


class DefaultPagination(LimitOffsetPagination):
    max_limit = 500
    default_limit = 500


class GasStationView(APIView):
    @swagger_auto_schema(responses={200: GasPriceSerializer()})
    def get(self, request, format=None):
        """
        Gets current gas prices for the ethereum network (using last 200 blocks)
        `Lowest` and `fastest` are the lower and the higher gas prices found in those blocks
        The rest are percentiles on all the gas prices in the last blocks.
        `safe_low=percentile 30`, `standard=percentile 50` and `fast=percentile 75`
        """
        gas_station = GasStationProvider()
        gas_prices = gas_station.get_gas_prices()
        serializer = GasPriceSerializer(gas_prices)
        return Response(serializer.data, headers={"Cache-Control": f"max-age={60 * 4}"})


class GasStationHistoryView(ListAPIView):
    serializer_class = GasPriceSerializer
    pagination_class = DefaultPagination

    def get_queryset(self):
        from_date = self.request.query_params.get("fromDate")
        to_date = self.request.query_params.get("toDate")
        from_date = (
            parse_datetime(from_date)
            if from_date
            else timezone.now() - datetime.timedelta(days=30)
        )
        to_date = parse_datetime(to_date) if to_date else timezone.now()
        return GasPrice.objects.filter(created__range=[from_date, to_date]).order_by(
            "created"
        )

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(
                "fromDate",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                format="date-time",
                description="ISO 8601 date to filter stats from. If not set, 1 month before now",
            ),
            openapi.Parameter(
                "toDate",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                format="date-time",
                description="ISO 8601 date to filter stats to. If not set, now",
            ),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

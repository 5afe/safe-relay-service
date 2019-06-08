from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from .gas_station import GasStationProvider
from .serializers import GasPriceSerializer


class GasStationView(APIView):
    @swagger_auto_schema(responses={200: GasPriceSerializer()})
    def get(self, request, format=None):
        gas_station = GasStationProvider()
        gas_prices = gas_station.get_gas_prices()
        serializer = GasPriceSerializer(gas_prices)
        return Response(serializer.data)

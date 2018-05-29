from django.conf import settings
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .gas_station import GasStation
from .serializers import GasPriceSerializer


class GasStationView(APIView):
    renderer_classes = (JSONRenderer,)

    gas_station = GasStation(settings.ETHEREUM_NODE_URL, settings.GAS_STATION_NUMBER_BLOCKS)

    def get(self, request, format=None):
        gas_prices = self.gas_station.get_gas_prices()
        return Response(GasPriceSerializer(gas_prices).data)

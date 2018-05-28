from django.conf import settings
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .gas_station import GasStation
from .serializers import GasPriceSerializer


class GasStationView(APIView):
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        gas_prices = GasStation(settings.ETHEREUM_NODE_URL).get_gas_prices()
        if gas_prices:
            return Response(GasPriceSerializer(gas_prices).data)
        else:
            return Response({'error': 'Gas Price not calculated yet. Retry in a few minutes'})

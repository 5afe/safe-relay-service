from django.conf import settings
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from safe_relay_service.version import __version__


class AboutView(APIView):
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        content = {
            'name': 'Safe Relay Service',
            'version': __version__,
            'api_version': self.request.version,
            'settings': {
                'ETH_HASH_PREFIX ': settings.ETH_HASH_PREFIX,
            }
        }
        return Response(content)

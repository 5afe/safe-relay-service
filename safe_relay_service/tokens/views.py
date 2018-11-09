from rest_framework import generics

from .models import Token
from .serializers import TokenSerializer


class TokenView(generics.ListAPIView):
    serializer_class = TokenSerializer

    def get_queryset(self):
        return Token.objects.all().order_by('relevance')

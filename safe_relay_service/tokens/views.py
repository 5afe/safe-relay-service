import django_filters.rest_framework
from rest_framework import filters, generics

from .filters import TokenFilter
from .models import Token
from .serializers import TokenSerializer


class TokenView(generics.ListAPIView):
    serializer_class = TokenSerializer
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    filterset_class = TokenFilter
    search_fields = ('name', 'symbol')
    ordering_fields = '__all__'
    ordering = ('relevance',)
    queryset = Token.objects.all()

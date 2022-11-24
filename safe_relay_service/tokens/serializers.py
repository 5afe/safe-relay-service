from rest_framework import serializers

from .models import Token


class TokenSerializer(serializers.ModelSerializer):
    logo_uri = serializers.SerializerMethodField()
    default = serializers.SerializerMethodField()

    class Meta:
        model = Token
        exclude = ["fixed_eth_conversion", "price_oracles", "relevance"]

    def get_logo_uri(self, obj: Token):
        return obj.get_full_logo_uri()

    def get_default(self, obj: Token):
        return obj.gas

from rest_framework import serializers

from safe_relay_service.tokens.models import Token


class TokenSerializer(serializers.ModelSerializer):
    logo_full_url = serializers.SerializerMethodField()

    class Meta:
        model = Token
        exclude = ['gas_token', 'fixed_eth_conversion', 'relevance']

    def get_logo_full_url(self, obj: Token):
        return obj.get_full_logo_url()

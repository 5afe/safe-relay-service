import os

from rest_framework import exceptions, status
from rest_framework.permissions import AllowAny
from rest_framework.renderers import CoreJSONRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.schemas import SchemaGenerator
from rest_framework.views import APIView
from rest_framework_swagger import renderers
from rest_framework_swagger.renderers import OpenAPICodec
from rest_framework_swagger.renderers import \
    OpenAPIRenderer as BaseOpenAPIRenderer


def get_swagger_view(title=None, url=None, patterns=None, urlconf=None):
    """
    Returns schema view which renders Swagger/OpenAPI.
    """
    class OpenAPIRenderer(BaseOpenAPIRenderer):
        def render(self, data, accepted_media_type=None, renderer_context=None):
            if renderer_context['response'].status_code != status.HTTP_200_OK:
                return JSONRenderer().render(data)

            request_scheme = renderer_context['request']._request._get_scheme()
            scheme = os.getenv('SWAGGER_SCHEME_PROTOCOL', request_scheme)
            self.scheme = scheme

            extra = self.get_customizations()

            return OpenAPICodec().encode(data, extra=extra)

        def get_customizations(self, *args, **kwargs):
            data = super(OpenAPIRenderer, self).get_customizations()
            data["schemes"] = [self.scheme]
            return data


    class SwaggerSchemaView(APIView):
        _ignore_model_permissions = True
        exclude_from_schema = True
        permission_classes = [AllowAny]
        renderer_classes = [
            CoreJSONRenderer,
            OpenAPIRenderer,
            renderers.SwaggerUIRenderer
        ]

        def get(self, request):
            generator = SchemaGenerator(
                title=title,
                url=url,
                patterns=patterns,
                urlconf=urlconf
            )
            schema = generator.get_schema(request=request)

            if not schema:
                raise exceptions.ValidationError(
                    'The schema generator did not return a schema Document'
                )

            return Response(schema)

    return SwaggerSchemaView.as_view()

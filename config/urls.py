from django.conf import settings
from django.conf.urls import include, url
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse
from django.views import defaults as default_views
from django.views.decorators.cache import cache_control

from drf_yasg import openapi
from drf_yasg.views import get_schema_view

schema_view = get_schema_view(
    openapi.Info(
        title='Gnosis Safe Relay API',
        default_version='v1',
        description='API to manage creation of safes and multisig transaction sending',
        contact=openapi.Contact(email='uxio@gnosis.pm'),
        license=openapi.License(name='MIT License'),
    ),
    validators=['flex', 'ssv'],
    public=True,
    # permission_classes=(permissions.AllowAny,),
)


schema_cache_timeout = 60 * 5  # 5 minutes
schema_cache_decorator = cache_control(max_age=schema_cache_timeout)

urlpatterns = [
    url(r'^$',
        schema_cache_decorator(schema_view.with_ui('swagger', cache_timeout=0)),
        name='schema-swagger-ui'),
    url(r'^swagger(?P<format>\.json|\.yaml)$',
        schema_cache_decorator(schema_view.without_ui(cache_timeout=schema_cache_timeout)),
        name='schema-json'),
    url(r'^redoc/$',
        schema_cache_decorator(schema_view.with_ui('redoc', cache_timeout=schema_cache_timeout)),
        name='schema-redoc'),
    url(settings.ADMIN_URL, admin.site.urls),
    url(r'^api/v1/', include('safe_relay_service.relay.urls', namespace='v1')),
    url(r'^api/v2/', include('safe_relay_service.relay.urls_v2', namespace='v2')),
    url(r'^api/v3/', include('safe_relay_service.relay.urls_v3', namespace='v3')),
    url(r'^check/', lambda request: HttpResponse("Ok"), name='check'),
]

if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        url(
            r"^400/$",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        url(
            r"^403/$",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        url(
            r"^404/$",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        url(r"^500/$", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [url(r"^__debug__/", include(debug_toolbar.urls))] + urlpatterns

admin.autodiscover()

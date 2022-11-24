from django.conf import settings
from django.conf.urls import include
from django.contrib import admin
from django.http import HttpResponse
from django.urls import re_path
from django.views import defaults as default_views

from drf_yasg import openapi
from drf_yasg.views import get_schema_view

schema_view = get_schema_view(
    openapi.Info(
        title="Gnosis Safe Relay API",
        default_version="v1",
        description="API to manage creation of safes and multisig transaction sending",
        contact=openapi.Contact(email="uxio@gnosis.pm"),
        license=openapi.License(name="MIT License"),
    ),
    validators=["flex", "ssv"],
    public=True,
    # permission_classes=(permissions.AllowAny,),
)


schema_cache_timeout = 60 * 5  # 5 minutes

urlpatterns = [
    re_path(
        r"^$",
        schema_view.with_ui("swagger", cache_timeout=schema_cache_timeout),
        name="schema-swagger-ui",
    ),
    re_path(
        r"^swagger(?P<format>\.json|\.yaml)$",
        schema_view.without_ui(cache_timeout=schema_cache_timeout),
        name="schema-json",
    ),
    re_path(
        r"^redoc/$",
        schema_view.with_ui("redoc", cache_timeout=schema_cache_timeout),
        name="schema-redoc",
    ),
    re_path(settings.ADMIN_URL, admin.site.urls),
    re_path(r"^api/v1/", include("safe_relay_service.relay.urls", namespace="v1")),
    re_path(r"^api/v2/", include("safe_relay_service.relay.urls_v2", namespace="v2")),
    re_path(r"^api/v3/", include("safe_relay_service.relay.urls_v3", namespace="v3")),
    re_path(r"^check/", lambda request: HttpResponse("Ok"), name="check"),
]

if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        re_path(
            r"^400/$",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        re_path(
            r"^403/$",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        re_path(
            r"^404/$",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        re_path(r"^500/$", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
            re_path(r"^__debug__/", include(debug_toolbar.urls))
        ] + urlpatterns

admin.autodiscover()

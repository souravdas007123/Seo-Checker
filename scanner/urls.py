from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("scan/<uuid:scan_id>/", views.report, name="report"),
    path("scan/<uuid:scan_id>/stream/", views.stream, name="stream"),
    path("scan/<uuid:scan_id>/diff/", views.diff, name="diff"),
]

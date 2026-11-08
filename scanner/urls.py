from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("scan/<uuid:scan_id>/", views.report, name="report"),
    path("scan/<uuid:scan_id>/stream/", views.stream, name="stream"),
    path("scan/<uuid:scan_id>/diff/", views.diff, name="diff"),
    path("signup/", views.signup, name="signup"),
    path("login/", views.LoginViewClaim.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),  # Django 5: sirf POST
    path("history/", views.history, name="history"),
    path("healthz/", views.healthz, name="healthz"),
    path("robots.txt", views.robots_txt, name="robots"),
]

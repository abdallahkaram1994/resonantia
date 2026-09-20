from django.urls import path

from catalog import views

urlpatterns = [
    path("search/", views.search, name="search"),
]

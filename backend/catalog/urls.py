from django.urls import path

from catalog import views

urlpatterns = [
    path("search/", views.search, name="search"),
    path("items/<int:item_id>/", views.item_detail, name="item-detail"),
    path("items/<int:item_id>/similar/", views.item_similar, name="item-similar"),
]

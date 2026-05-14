from django.urls import path
from . import views

urlpatterns = [
    path("chatbot/", views.chatbot, name="chatbot"),
    path("welcome-api/", views.welcome_api, name="welcome_api"),
    path("chatbot-api/", views.chatbot_api, name="chatbot_api"),
    path("set-location/", views.set_location_api, name="set_location_api"),
    path("places/", views.places_api, name="places_api"),
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("nearby_places/", views.nearby_places_view, name="nearby_places"),
    path("history/", views.history_view, name="history"),
    path("history/<int:history_id>/", views.history_detail_api, name="history_detail"),
    path("new-chat/", views.new_chat_api, name="new_chat"),
    path("history-api/", views.history_api, name="history_api"),
    path("admin-panel/", views.admin_dashboard, name="admin_dashboard"),
    path("delete-user/<int:user_id>/", views.delete_user, name="delete_user"),
]
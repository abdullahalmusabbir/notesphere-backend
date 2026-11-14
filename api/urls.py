from django.urls import path

from . import views

urlpatterns = [
    # auth
    path("auth/register/", views.RegisterView.as_view(), name="auth-register"),
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/refresh/", views.RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/forgot-password/", views.ForgotPasswordView.as_view(), name="auth-forgot-password"),
    path("auth/reset-password/", views.ResetPasswordView.as_view(), name="auth-reset-password"),
    path("auth/me/", views.MeView.as_view(), name="auth-me"),

    # users
    path("users/me/", views.ProfileView.as_view(), name="user-profile"),
    path("users/<str:user_id>/posts/", views.UserPostsView.as_view(), name="user-posts"),

    # notes
    path("notes/", views.NoteListCreateView.as_view(), name="note-list"),
    path("notes/<str:note_id>/", views.NoteDetailView.as_view(), name="note-detail"),

    # posts
    path("posts/", views.PostListCreateView.as_view(), name="post-list"),
    path("posts/<str:post_id>/", views.PostDetailView.as_view(), name="post-detail"),

    # admin
    path("admin/users/", views.AdminUserListCreateView.as_view(), name="admin-user-list"),
    path("admin/users/<str:user_id>/", views.AdminUserDetailView.as_view(), name="admin-user-detail"),
    path("admin/interests/", views.AdminInterestListView.as_view(), name="admin-interests"),
]
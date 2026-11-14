from django.conf import settings
from django.http import JsonResponse
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotAuthenticated, NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from . import admins
from . import docker_services as services
from .authentications import *
from .models import USER_SELF_EDITABLE_FIELDS, USER_ADMIN_EDITABLE_FIELDS
from .permissions import *
from .serializers import *
from .authentications import JWTAuthentication


# --------------------------------------------------------------------- helpers
def success(data=None, message="Operation completed successfully",
            status_code=status.HTTP_200_OK) -> Response:
    return Response(
        {"success": True, "message": message, "data": {} if data is None else data},
        status=status_code,
    )


def paginated(data, params: dict, total: int, message="Data retrieved successfully") -> Response:
    return Response({
        "success": True,
        "message": message,
        "data": data,
        "pagination": pagination_meta(params["page"], params["page_size"], total),
    })


def deleted() -> Response:
    return Response(status=status.HTTP_204_NO_CONTENT)


def read_query(serializer_class, request) -> dict:
    serializer = serializer_class(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def read_body(serializer_class, request, *, partial: bool = False) -> dict:
    serializer = serializer_class(data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def client_ip(request) -> str:
    """Client address for throttling. X-Forwarded-For is only trusted when
    NUM_PROXIES says how many proxies sit in front of the app, because the
    header is otherwise controlled by the client."""
    if settings.NUM_PROXIES:
        hops = [h.strip() for h in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if h.strip()]
        if len(hops) >= settings.NUM_PROXIES:
            return hops[-settings.NUM_PROXIES][:45]
    return (request.META.get("REMOTE_ADDR") or "unknown")[:45]


def not_found(request, exception=None):
    return JsonResponse({"success": False, "message": "Resource not found.", "errors": {}}, status=404)


def server_error(request):
    return JsonResponse({"success": False, "message": "Something went wrong.", "errors": {}}, status=500)


# ------------------------------------------------------------------------ auth
class RegisterView(APIView):
    # No authentication here, so an old or broken token cannot block sign up.
    authentication_classes = []
    permission_classes = [PublicEndpoint]

    @extend_schema(tags=["Auth"], request=RegisterSerializer, responses={201: UserSerializer},
                   summary="Create a new account")
    def post(self, request):
        data = read_body(RegisterSerializer, request)
        user = services.register_user(data)
        return success(UserSerializer(user).data, "Registration successful", status.HTTP_201_CREATED)


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [PublicEndpoint]

    @extend_schema(tags=["Auth"], request=LoginSerializer, summary="Login with email and password")
    def post(self, request):
        data = read_body(LoginSerializer, request)
        user = services.authenticate_user(data["email"], data["password"], client_ip(request))
        tokens = issue_token_pair(user["_id"])
        return success({**tokens, "user": UserSerializer(user).data}, "Login successful")


class RefreshView(APIView):
    authentication_classes = []
    permission_classes = [PublicEndpoint]

    @extend_schema(tags=["Auth"], request=RefreshTokenSerializer,
                   summary="Rotate the refresh token and get a new token pair")
    def post(self, request):
        data = read_body(RefreshTokenSerializer, request)
        user, tokens = rotate_refresh_token(data["refresh"])
        return success({**tokens, "user": UserSerializer(user).data}, "Token refreshed successfully")


class LogoutView(APIView):
    permission_classes = [IsAuthenticatedUser]

    @extend_schema(tags=["Auth"], request=RefreshTokenSerializer, summary="Revoke the refresh token")
    def post(self, request):
        data = read_body(RefreshTokenSerializer, request)
        revoke_refresh_token(data["refresh"], request.user.id)
        return success(message="Logged out successfully")


class ForgotPasswordView(APIView):
    authentication_classes = []
    permission_classes = [PublicEndpoint]

    @extend_schema(tags=["Auth"], request=ForgotPasswordSerializer, summary="Request a password reset link")
    def post(self, request):
        data = read_body(ForgotPasswordSerializer, request)
        services.request_password_reset(data["email"], client_ip(request))
        return success(message="If an account with that email exists, a reset link has been sent")


class ResetPasswordView(APIView):
    authentication_classes = []
    permission_classes = [PublicEndpoint]

    @extend_schema(tags=["Auth"], request=ResetPasswordSerializer, summary="Set a new password with a reset token")
    def post(self, request):
        data = read_body(ResetPasswordSerializer, request)
        services.reset_password(data["token"], data["new_password"])
        return success(message="Password has been reset successfully")


class MeView(APIView):
    permission_classes = [IsAuthenticatedUser]

    @extend_schema(tags=["Auth"], responses={200: UserSerializer}, summary="Current user")
    def get(self, request):
        return success(UserSerializer(request.user.document).data, "Profile retrieved successfully")


# ----------------------------------------------------------------------- users
class ProfileView(APIView):
    """Own profile. Only USER_SELF_EDITABLE_FIELDS can change here, the
    target user is always the one from the JWT (never an id from the client)."""

    permission_classes = [IsAuthenticatedUser]

    @extend_schema(tags=["Users"], responses={200: UserSerializer}, summary="View own profile")
    def get(self, request):
        return success(UserSerializer(request.user.document).data, "Profile retrieved successfully")

    @extend_schema(tags=["Users"], request=UserUpdateSerializer, responses={200: UserSerializer},
                   summary="Update own profile")
    def put(self, request):
        return self._update(request, partial=False)

    @extend_schema(tags=["Users"], request=UserUpdateSerializer, responses={200: UserSerializer},
                   summary="Partially update own profile")
    def patch(self, request):
        return self._update(request, partial=True)

    def _update(self, request, *, partial: bool):
        data = read_body(UserUpdateSerializer, request, partial=partial)
        user = admins.update_user(
            request.user.id,
            data,
            allowed_fields=USER_SELF_EDITABLE_FIELDS,
            acting_user_id=request.user.id,
        )
        return success(UserSerializer(user).data, "Profile updated successfully")


class UserPostsView(APIView):
    """Scenario 2. Public, but the requester (if any) decides which posts show."""

    permission_classes = [PublicEndpoint]

    @extend_schema(tags=["Posts"], parameters=[PaginationSerializer],
                   responses={200: UserWithPostsSerializer}, summary="A user with their posts")
    def get(self, request, user_id):
        params = read_query(PaginationSerializer, request)
        profile, total = services.get_user_with_posts(
            user_id, request.user, params["page"], params["page_size"]
        )
        return paginated(UserWithPostsSerializer(profile).data, params, total)


# ----------------------------------------------------------------------- notes
class NoteListCreateView(APIView):

    @extend_schema(tags=["Notes"], parameters=[NoteQuerySerializer], responses={200: NoteSerializer(many=True)},
                   summary="List own notes (admins: all notes)")
    def get(self, request):
        params = read_query(NoteQuerySerializer, request)
        notes, total = services.list_notes(request.user, params)
        return paginated(NoteSerializer(notes, many=True).data, params, total)

    @extend_schema(tags=["Notes"], request=NoteCreateSerializer, responses={201: NoteSerializer},
                   summary="Create a note")
    def post(self, request):
        data = read_body(NoteCreateSerializer, request)
        note = services.create_note(request.user.id, data)
        return success(NoteSerializer(note).data, "Note created successfully", status.HTTP_201_CREATED)


class NoteDetailView(APIView):
    # Ownership is enforced inside every query through ownership_filter().
    permission_classes = [IsOwnerOrAdmin]

    @extend_schema(tags=["Notes"], responses={200: NoteSerializer}, summary="Get a note")
    def get(self, request, note_id):
        note = services.get_note(request.user, note_id)
        return success(NoteSerializer(note).data, "Note retrieved successfully")

    @extend_schema(tags=["Notes"], request=NoteUpdateSerializer, responses={200: NoteSerializer},
                   summary="Replace a note")
    def put(self, request, note_id):
        data = read_body(NoteUpdateSerializer, request)
        note = services.update_note(request.user, note_id, data)
        return success(NoteSerializer(note).data, "Note updated successfully")

    @extend_schema(tags=["Notes"], request=NoteUpdateSerializer, responses={200: NoteSerializer},
                   summary="Partially update a note")
    def patch(self, request, note_id):
        data = read_body(NoteUpdateSerializer, request, partial=True)
        note = services.update_note(request.user, note_id, data)
        return success(NoteSerializer(note).data, "Note updated successfully")

    @extend_schema(tags=["Notes"], responses={204: None}, summary="Delete a note")
    def delete(self, request, note_id):
        services.delete_note(request.user, note_id)
        return deleted()


# ----------------------------------------------------------------------- posts
class PostListCreateView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [CanCreatePost]

    @extend_schema(tags=["Posts"], parameters=[PostQuerySerializer], responses={200: PostListSerializer(many=True)},
                   summary="Public posts (admins can see drafts too)")
    def get(self, request):
        params = read_query(PostQuerySerializer, request)
        posts, total = services.list_posts(request.user, params)
        return paginated(PostListSerializer(posts, many=True).data, params, total)

    @extend_schema(tags=["Posts"], request=PostCreateSerializer, responses={201: PostSerializer},
                   summary="Create a post")
    def post(self, request):
        data = read_body(PostCreateSerializer, request)
        post = services.create_post(request.user.id, data)
        return success(PostSerializer(post).data, "Post created successfully", status.HTTP_201_CREATED)


class PostDetailView(APIView):
    authentication_classes = [JWTAuthentication]   # add
    permission_classes = [IsPublishedOrOwnerOrAdmin]

    def _load(self, request, post_id):
        post = services.get_post(post_id)
        try:
            self.check_object_permissions(request, post)
        except (PermissionDenied, NotAuthenticated):
            # A draft must look like it does not exist to everybody else.
            if not post.get("is_published"):
                raise NotFound("Post not found.")
            raise
        return post

    @extend_schema(tags=["Posts"], responses={200: PostSerializer}, summary="Get a post")
    def get(self, request, post_id):
        post = self._load(request, post_id)
        return success(PostSerializer(post).data, "Post retrieved successfully")

    @extend_schema(tags=["Posts"], request=PostUpdateSerializer, responses={200: PostSerializer},
                   summary="Replace a post")
    def put(self, request, post_id):
        return self._update(request, post_id, partial=False)

    @extend_schema(tags=["Posts"], request=PostUpdateSerializer, responses={200: PostSerializer},
                   summary="Partially update a post")
    def patch(self, request, post_id):
        return self._update(request, post_id, partial=True)

    @extend_schema(tags=["Posts"], responses={204: None}, summary="Delete a post")
    def delete(self, request, post_id):
        post = self._load(request, post_id)
        services.delete_post(post["_id"], request.user)
        return deleted()

    def _update(self, request, post_id, *, partial: bool):
        post = self._load(request, post_id)
        data = read_body(PostUpdateSerializer, request, partial=partial)
        updated = services.update_post(post["_id"], request.user, data)
        return success(PostSerializer(updated).data, "Post updated successfully")


# ----------------------------------------------------------------------- admin
class AdminUserListCreateView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(tags=["Admin"], parameters=[UserQuerySerializer], responses={200: UserSerializer(many=True)},
                   summary="List users")
    def get(self, request):
        params = read_query(UserQuerySerializer, request)
        users, total = admins.list_users(
            page=params["page"],
            page_size=params["page_size"],
            search=params.get("search"),
            role=params.get("role"),
            is_active=params.get("is_active"),
            ordering=params["ordering"],
        )
        return paginated(UserSerializer(users, many=True).data, params, total)

    @extend_schema(tags=["Admin"], request=AdminUserCreateSerializer, responses={201: UserSerializer},
                   summary="Create a user")
    def post(self, request):
        data = read_body(AdminUserCreateSerializer, request)
        user = admins.create_user(data)
        return success(UserSerializer(user).data, "User created successfully", status.HTTP_201_CREATED)


class AdminUserDetailView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(tags=["Admin"], responses={200: UserSerializer}, summary="Get a user")
    def get(self, request, user_id):
        return success(UserSerializer(admins.get_user(user_id)).data, "User retrieved successfully")

    @extend_schema(tags=["Admin"], request=AdminUserUpdateSerializer, responses={200: UserSerializer},
                   summary="Replace a user")
    def put(self, request, user_id):
        return self._update(request, user_id, partial=False)

    @extend_schema(tags=["Admin"], request=AdminUserUpdateSerializer, responses={200: UserSerializer},
                   summary="Partially update a user")
    def patch(self, request, user_id):
        return self._update(request, user_id, partial=True)

    @extend_schema(tags=["Admin"], responses={204: None}, summary="Delete a user")
    def delete(self, request, user_id):
        admins.delete_user(user_id, request.user.id)
        return deleted()

    def _update(self, request, user_id, *, partial: bool):
        data = read_body(AdminUserUpdateSerializer, request, partial=partial)
        user = admins.update_user(
            user_id,
            data,
            allowed_fields=USER_ADMIN_EDITABLE_FIELDS,
            acting_user_id=request.user.id,
        )
        return success(UserSerializer(user).data, "User updated successfully")


class AdminInterestListView(APIView):
    """Scenario 1."""

    permission_classes = [IsAdmin]

    @extend_schema(tags=["Admin"], parameters=[PaginationSerializer],
                   responses={200: InterestGroupSerializer(many=True)}, summary="Users grouped by interest")
    def get(self, request):
        params = read_query(PaginationSerializer, request)
        groups, total = services.group_users_by_interest(params["page"], params["page_size"])
        return paginated(InterestGroupSerializer(groups, many=True).data, params, total)
# apps/invitations/serializers.py
from rest_framework import serializers # type: ignore
from .models import TestInvitation


class TestSerializer(serializers.Serializer):
    """Serializer para datos básicos del test"""
    id = serializers.IntegerField()
    title = serializers.CharField()
    description = serializers.CharField()
    main_topic = serializers.CharField()
    sub_topic = serializers.CharField()
    specific_topic = serializers.CharField()
    level = serializers.CharField()


class InviterSerializer(serializers.Serializer):
    """Serializer para el usuario que invita"""
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        # obj is a plain dict when called from InvitationResponseSerializer
        if isinstance(obj, dict):
            return f"{obj.get('first_name', '')} {obj.get('last_name', '')}".strip()
        return f"{obj.first_name} {obj.last_name}".strip()


class GuestUserSerializer(serializers.Serializer):
    """Serializer para usuario invitado"""
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()


class InvitationSerializer(serializers.ModelSerializer):
    """Serializer principal para invitaciones"""
    test_title = serializers.CharField(source='test.title', read_only=True)
    inviter_name = serializers.CharField(source='invited_by.username', read_only=True)
    guest_name = serializers.SerializerMethodField()
    guest_user_id = serializers.PrimaryKeyRelatedField(source='guest_user', read_only=True)
    status = serializers.SerializerMethodField()
    invitation_url = serializers.SerializerMethodField()

    class Meta:
        model = TestInvitation
        fields = [
            'id', 'test', 'test_title', 'invited_by', 'inviter_name',
            'guest_user', 'guest_user_id', 'guest_name', 'message', 'token',
            'is_used', 'is_guest', 'expires_at', 'created_at', 'updated_at',
            'status', 'invitation_url',
        ]
        read_only_fields = ['token', 'created_at', 'updated_at']

    def get_guest_name(self, obj):
        return obj.guest_user.username if obj.guest_user else None

    def get_status(self, obj):
        return obj.status

    def get_invitation_url(self, obj):
        return obj.invitation_url


class CreateInvitationSerializer(serializers.Serializer):
    """Serializer para crear invitaciones"""
    test_id = serializers.IntegerField()
    message = serializers.CharField(required=False, allow_blank=True)

    def validate_test_id(self, value):
        from apps.test.models import Test
        if not Test.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError("Test no encontrado o inactivo")
        return value


class AcceptInvitationSerializer(serializers.Serializer):
    """Serializer para aceptar invitaciones"""
    as_guest = serializers.BooleanField(default=False, required=False)


class DeleteInvitationsSerializer(serializers.Serializer):
    """Serializer para eliminar múltiples invitaciones"""
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
    )


class InvitationFilterSerializer(serializers.Serializer):
    """Serializer para filtros de invitaciones"""
    page = serializers.IntegerField(min_value=1, required=False, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False, default=20)
    sort_by = serializers.CharField(required=False, default='created_at')
    sort_order = serializers.ChoiceField(choices=['asc', 'desc'], required=False, default='desc')
    search = serializers.CharField(required=False, allow_blank=True)
    test_id = serializers.IntegerField(required=False, allow_null=True)
    invited_by = serializers.IntegerField(required=False, allow_null=True)
    is_used = serializers.BooleanField(required=False, allow_null=True)
    is_guest = serializers.BooleanField(required=False, allow_null=True)
    status = serializers.ChoiceField(
        choices=['active', 'used', 'expired'],
        required=False,
        allow_null=True,
    )
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)


class InvitationResponseSerializer(serializers.Serializer):
    """Serializer para respuesta de check_invitation"""

    def to_representation(self, instance):
        """
        instance is a TestInvitation with select_related already done.
        Build a flat dict so downstream code can add extra keys (result, is_authenticated, etc.).
        """
        invitation = instance
        return {
            'invitation': InvitationSerializer(invitation).data,
            'test': {
                'id': invitation.test.id,
                'title': invitation.test.title,
                'description': invitation.test.description,
                'main_topic': invitation.test.main_topic,
                'sub_topic': invitation.test.sub_topic,
                'specific_topic': invitation.test.specific_topic,
                'level': invitation.test.level,
            },
            'inviter': {
                'id': invitation.invited_by.id,
                'username': invitation.invited_by.username,
                'email': invitation.invited_by.email,
                'first_name': invitation.invited_by.first_name,
                'last_name': invitation.invited_by.last_name,
                'full_name': f"{invitation.invited_by.first_name} {invitation.invited_by.last_name}".strip(),
            },
        }
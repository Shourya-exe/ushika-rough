from django.contrib.auth import get_user_model
from django.urls import reverse
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..media import preview_mime_type
from ..messaging import MEDIA_SEND_TYPES, SEND_TYPES, normalize_phone
from ..models import Contact, MediaAttachment, Message, MessageStatusEvent


class CurrentUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()
        fields = ["id", "username", "is_staff", "is_superuser", "last_login"]


class ContactSerializer(serializers.ModelSerializer):
    message_count = serializers.IntegerField(read_only=True)
    last_message_at = serializers.DateTimeField(read_only=True, allow_null=True)
    level = serializers.SlugRelatedField(slug_field="name", read_only=True, help_text="Set in the Django admin.")

    class Meta:
        model = Contact
        fields = [
            "id", "wa_id", "profile_name", "level", "message_count", "last_message_at", "created_at", "updated_at",
        ]


class ContactSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ["id", "wa_id", "profile_name"]


class MediaAttachmentSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()

    class Meta:
        model = MediaAttachment
        fields = [
            "id",
            "message",
            "media_id",
            "media_type",
            "mime_type",
            "sha256",
            "filename",
            "caption",
            "file_size",
            "download_status",
            "download_attempts",
            "last_error",
            "downloaded_at",
            "download_url",
            "preview_url",
            "created_at",
        ]

    def _file_url(self, obj, view_name):
        """Null when this user can't get the file: it isn't saved, and only superusers get unsaved files."""
        request = self.context.get("request")
        saved = obj.download_status == MediaAttachment.DownloadStatus.DOWNLOADED and obj.file
        if not saved and not (request and request.user.is_superuser):
            return None
        url = reverse(view_name, args=[obj.pk])
        return request.build_absolute_uri(url) if request else url

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_download_url(self, obj):
        return self._file_url(obj, "api:attachment-download")

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_preview_url(self, obj):
        return self._file_url(obj, "api:attachment-preview") if preview_mime_type(obj) else None


class MessageStatusEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageStatusEvent
        fields = [
            "id",
            "message",
            "wa_message_id",
            "status",
            "timestamp",
            "recipient_id",
            "conversation_id",
            "pricing_category",
            "error_code",
            "error_title",
            "error_details",
            "created_at",
        ]


class MessageSerializer(serializers.ModelSerializer):
    contact = ContactSummarySerializer(read_only=True)
    attachments = MediaAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Message
        fields = [
            "id",
            "wa_message_id",
            "contact",
            "direction",
            "message_type",
            "status",
            "body",
            "context_wa_message_id",
            "timestamp",
            "status_updated_at",
            "error_code",
            "error_title",
            "error_details",
            "attachments",
            "created_at",
        ]


class MessageDetailSerializer(MessageSerializer):
    status_events = MessageStatusEventSerializer(many=True, read_only=True)
    sent_by = serializers.SlugRelatedField(slug_field="username", read_only=True)

    class Meta(MessageSerializer.Meta):
        fields = MessageSerializer.Meta.fields + [
            "phone_number_id",
            "idempotency_key",
            "sent_by",
            "payload",
            "status_events",
        ]


class SendMessageSerializer(serializers.Serializer):
    to = serializers.CharField(help_text="Recipient phone number in international format, e.g. 16315551234.")
    type = serializers.ChoiceField(choices=sorted(SEND_TYPES))
    text = serializers.CharField(required=False, allow_blank=False, max_length=4096)
    preview_url = serializers.BooleanField(required=False, default=False)
    template_name = serializers.CharField(required=False, max_length=512)
    language_code = serializers.CharField(required=False, default="en_US", max_length=16)
    components = serializers.ListField(child=serializers.DictField(), required=False)
    media_link = serializers.URLField(required=False)
    media_id = serializers.CharField(required=False, max_length=255)
    caption = serializers.CharField(required=False, max_length=1024)
    filename = serializers.CharField(required=False, max_length=255)
    reply_to = serializers.CharField(required=False, max_length=255, help_text="wamid of the message to reply to.")
    idempotency_key = serializers.CharField(
        required=False, max_length=64, help_text="Retrying with the same key returns the original message."
    )

    def validate_to(self, value):
        digits = normalize_phone(value)
        if not 7 <= len(digits) <= 15:
            raise serializers.ValidationError("Enter a phone number in international format (7-15 digits).")
        return digits

    def validate_media_link(self, value):
        if not value.lower().startswith("https://"):
            raise serializers.ValidationError("WhatsApp only fetches media over HTTPS.")
        return value

    def validate(self, attrs):
        message_type = attrs["type"]
        errors = {}
        if message_type == "text" and not attrs.get("text"):
            errors["text"] = "Required for text messages."
        if message_type == "template" and not attrs.get("template_name"):
            errors["template_name"] = "Required for template messages."
        if message_type in MEDIA_SEND_TYPES:
            if bool(attrs.get("media_link")) == bool(attrs.get("media_id")):
                errors["media_link"] = "Provide exactly one of media_link or media_id."
            if attrs.get("caption") and message_type not in {"image", "video", "document"}:
                errors["caption"] = f"{message_type} messages cannot have a caption."
            if attrs.get("filename") and message_type != "document":
                errors["filename"] = "Only document messages take a filename."
        for field in ("text", "preview_url"):
            if message_type != "text" and attrs.get(field):
                errors[field] = "Only used for text messages."
        for field in ("template_name", "components"):
            if message_type != "template" and attrs.get(field):
                errors[field] = "Only used for template messages."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

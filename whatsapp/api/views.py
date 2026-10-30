import json
import os

import django_filters
from django.db.models import Count, F, Max
from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response

from .. import media, messaging
from ..models import Contact, MediaAttachment, Message, MessageStatusEvent
from .serializers import (
    ContactSerializer,
    CurrentUserSerializer,
    MediaAttachmentSerializer,
    MessageDetailSerializer,
    MessageSerializer,
    MessageStatusEventSerializer,
    SendMessageSerializer,
)


@extend_schema(responses=CurrentUserSerializer)
@api_view(["GET"])
def current_user(request):
    """Who the token or session belongs to. A 401 means the login is not valid."""
    return Response(CurrentUserSerializer(request.user).data)


class BinaryRenderer(BaseRenderer):
    """Lets file downloads satisfy any Accept header; JSON errors still render as JSON."""

    media_type = "*/*"
    format = "bin"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data if isinstance(data, bytes) else json.dumps(data).encode()


class MediaFetchFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Could not fetch the file from WhatsApp."


class MessageFilter(django_filters.FilterSet):
    wa_id = django_filters.CharFilter(field_name="contact__wa_id")
    since = django_filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="gte")
    until = django_filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="lte")

    class Meta:
        model = Message
        fields = ["direction", "message_type", "status", "contact"]


class ContactViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ContactSerializer
    lookup_value_regex = r"\d+"
    filterset_fields = ["wa_id", "level"]
    search_fields = ["wa_id", "profile_name"]
    ordering_fields = ["last_message_at", "created_at", "profile_name"]

    def get_queryset(self):
        return Contact.objects.select_related("level").annotate(
            message_count=Count("messages"), last_message_at=Max("messages__timestamp")
        ).order_by(F("last_message_at").desc(nulls_last=True), "-id")


class MessageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Message.objects.select_related("contact", "sent_by").prefetch_related("attachments")
    lookup_value_regex = r"\d+"
    filterset_class = MessageFilter
    search_fields = ["body", "contact__wa_id", "contact__profile_name"]
    ordering_fields = ["timestamp", "created_at"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return MessageDetailSerializer
        if self.action == "send":
            return SendMessageSerializer
        if self.action == "statuses":
            return MessageStatusEventSerializer
        return MessageSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("status_events")
        return queryset

    @extend_schema(
        request=SendMessageSerializer,
        responses={
            201: MessageDetailSerializer,
            200: OpenApiResponse(MessageDetailSerializer, description="Replay of an earlier idempotency_key."),
            502: OpenApiResponse(MessageDetailSerializer, description="Meta rejected the send; stored as failed."),
        },
    )
    @action(detail=False, methods=["post"])
    def send(self, request):
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        message, created = messaging.send_message(
            to=data.pop("to"),
            message_type=data.pop("type"),
            idempotency_key=data.pop("idempotency_key", None),
            user=request.user,
            **data,
        )
        if not created:
            response_status = status.HTTP_200_OK
        elif message.status == Message.Status.FAILED:
            response_status = status.HTTP_502_BAD_GATEWAY
        else:
            response_status = status.HTTP_201_CREATED
        body = MessageDetailSerializer(message, context=self.get_serializer_context()).data
        return Response(body, status=response_status)

    @extend_schema(responses=MessageStatusEventSerializer(many=True))
    @action(detail=True, methods=["get"])
    def statuses(self, request, pk=None):
        events = self.get_object().status_events.all()
        page = self.paginate_queryset(events)
        serializer = MessageStatusEventSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class MediaAttachmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MediaAttachment.objects.all()
    serializer_class = MediaAttachmentSerializer
    lookup_value_regex = r"\d+"
    filterset_fields = ["download_status", "media_type", "message"]
    ordering_fields = ["created_at", "downloaded_at"]

    def _open_file(self, attachment):
        """(handle, filename, mime type) from storage, or for a superuser straight from WhatsApp if not saved."""
        if attachment.download_status == MediaAttachment.DownloadStatus.DOWNLOADED and attachment.file:
            try:
                handle = attachment.file.open("rb")
            except FileNotFoundError:
                raise NotFound("The stored file is missing from storage.")
            return handle, os.path.basename(attachment.file.name), attachment.mime_type
        if not self.request.user.is_superuser:
            raise NotFound("This attachment has not been downloaded.")
        try:
            handle, mime_type = media.fetch_unsaved(attachment)
        except media.MediaDownloadError as exc:
            raise MediaFetchFailed(str(exc))
        return handle, media.safe_filename(attachment, mime_type), mime_type

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY, 404: None, 502: None})
    @action(detail=True, methods=["get"], renderer_classes=[JSONRenderer, BinaryRenderer])
    def download(self, request, pk=None):
        """The file, as a download. Superusers also get files that aren't saved, fetched from WhatsApp and not kept."""
        handle, filename, mime_type = self._open_file(self.get_object())
        return FileResponse(
            handle, as_attachment=True, filename=filename, content_type=mime_type or "application/octet-stream"
        )

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY, 404: None, 502: None})
    @action(detail=True, methods=["get"], renderer_classes=[JSONRenderer, BinaryRenderer])
    def preview(self, request, pk=None):
        """The file, for showing in the browser. Same access as download; only safe types (see preview_url)."""
        attachment = self.get_object()
        preview_type = media.preview_mime_type(attachment)
        if not preview_type:
            raise NotFound("This file type can't be previewed. Download it instead.")
        handle, filename, _ = self._open_file(attachment)
        response = FileResponse(handle, filename=filename, content_type=preview_type)
        response["X-Frame-Options"] = "SAMEORIGIN"  # the admin embeds PDFs and text files in a frame
        return response

    @extend_schema(
        request=None,
        responses={
            200: MediaAttachmentSerializer,
            403: OpenApiResponse(description="The contact's level (or, for other media, your role) forbids saving it."),
            502: OpenApiResponse(MediaAttachmentSerializer, description="Download failed; see last_error."),
        },
    )
    @action(detail=True, methods=["post"])
    def save(self, request, pk=None):
        """Fetch the file from WhatsApp and save it to local storage. Also retries a failed save.

        Images and PDFs need a contact level that allows them; other media needs a superuser.
        """
        attachment = self.get_object()
        refusal = media.save_refusal(attachment, admin=request.user.is_superuser)
        if refusal:
            raise PermissionDenied(refusal)
        outcome = media.download_attachment(attachment)
        serializer = self.get_serializer(attachment)
        return Response(serializer.data, status=status.HTTP_200_OK if outcome.ok else status.HTTP_502_BAD_GATEWAY)


class MessageStatusEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MessageStatusEvent.objects.all()
    serializer_class = MessageStatusEventSerializer
    lookup_value_regex = r"\d+"
    filterset_fields = ["wa_message_id", "status", "message"]
    ordering_fields = ["timestamp", "created_at"]

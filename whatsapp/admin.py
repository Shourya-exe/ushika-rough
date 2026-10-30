from django.contrib import admin, messages
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html

from . import media, processing
from .models import Contact, ContactLevel, MediaAttachment, Message, MessageStatusEvent, WebhookEvent


def file_links(attachment):
    """Preview and Download links. Both go through the API, so only logged-in users get the file."""
    if not attachment.pk:
        return "-"
    download = reverse("api:attachment-download", args=[attachment.pk])
    if not media.preview_mime_type(attachment):
        return format_html('<a href="{}">Download</a>', download)
    preview = reverse("api:attachment-preview", args=[attachment.pk])
    return format_html('<a href="{}" target="_blank" rel="noopener">Preview</a> | <a href="{}">Download</a>',
                       preview, download)


class MediaAttachmentInline(admin.TabularInline):
    model = MediaAttachment
    extra = 0
    can_delete = False
    fields = ["media_type", "mime_type", "filename", "links", "download_status", "download_attempts", "last_error"]
    readonly_fields = fields

    @admin.display(description="File")
    def links(self, obj):
        return file_links(obj)


class MessageStatusEventInline(admin.TabularInline):
    model = MessageStatusEvent
    extra = 0
    can_delete = False
    fields = ["status", "timestamp", "error_code", "error_title"]
    readonly_fields = fields


@admin.register(ContactLevel)
class ContactLevelAdmin(admin.ModelAdmin):
    list_display = ["name", "can_save_images", "can_save_pdfs", "contact_count"]
    search_fields = ["name"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(contact_count=Count("contacts"))

    @admin.display(description="Contacts", ordering="contact_count")
    def contact_count(self, obj):
        return obj.contact_count


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ["wa_id", "profile_name", "level", "created_at", "updated_at"]
    list_editable = ["level"]
    list_filter = ["level"]
    list_select_related = ["level"]
    search_fields = ["wa_id", "profile_name"]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["id", "timestamp", "direction", "contact", "message_type", "status", "short_body"]
    list_filter = ["direction", "message_type", "status"]
    search_fields = ["wa_message_id", "body", "contact__wa_id", "contact__profile_name"]
    list_select_related = ["contact"]
    readonly_fields = ["created_at", "updated_at"]
    raw_id_fields = ["contact", "sent_by"]
    inlines = [MediaAttachmentInline, MessageStatusEventInline]

    @admin.display(description="Body")
    def short_body(self, obj):
        return obj.body[:60]


@admin.register(MediaAttachment)
class MediaAttachmentAdmin(admin.ModelAdmin):
    list_display = ["id", "links", "contact", "media_type", "filename", "file_size", "download_status", "created_at"]
    list_filter = ["download_status", "media_type"]
    list_select_related = ["message__contact"]
    search_fields = ["media_id", "filename"]
    raw_id_fields = ["message"]
    # `file` is left out: the stock widget links to a URL that doesn't exist, as media is never publicly served.
    fields = ["preview", "links", "message", "media_id", "media_type", "mime_type", "sha256", "filename", "caption",
              "file_size", "download_status", "download_attempts", "last_error", "downloaded_at"]
    readonly_fields = ["preview", "links"]
    actions = ["save_file"]

    @admin.display(description="Contact", ordering="message__contact")
    def contact(self, obj):
        return obj.message.contact

    @admin.display(description="File")
    def links(self, obj):
        return file_links(obj)

    @admin.display(description="Preview")
    def preview(self, obj):
        mime_type = media.preview_mime_type(obj)
        if not obj.pk or not mime_type:
            return "This file type can't be shown in the browser. Download it instead."
        url = reverse("api:attachment-preview", args=[obj.pk])
        kind = mime_type.split("/")[0]
        if kind == "image":
            return format_html('<img src="{}" alt="Preview not available" style="max-width:100%;max-height:70vh">', url)
        if kind == "video":
            return format_html('<video src="{}" controls preload="none" style="max-width:100%;max-height:70vh"></video>',
                               url)
        if kind == "audio":
            return format_html('<audio src="{}" controls preload="none"></audio>', url)
        # The admin's form column has no fixed width to take a percentage of, so size from the viewport.
        return format_html('<iframe src="{}" title="File preview" '
                           'style="width:max(320px,calc(100vw - 600px));height:70vh"></iframe>', url)

    @admin.action(description="Save file now (if the contact's level allows it)")
    def save_file(self, request, queryset):
        saved = failed = refused = 0
        for attachment in queryset.select_related("message__contact__level"):
            if media.save_refusal(attachment, admin=request.user.is_superuser):
                refused += 1
            elif media.download_attachment(attachment).ok:
                saved += 1
            else:
                failed += 1
        self.message_user(request, f"{saved} saved, {failed} failed, {refused} not allowed.", messages.INFO)


@admin.register(MessageStatusEvent)
class MessageStatusEventAdmin(admin.ModelAdmin):
    list_display = ["wa_message_id", "status", "timestamp", "recipient_id", "error_code"]
    list_filter = ["status"]
    search_fields = ["wa_message_id", "recipient_id"]
    raw_id_fields = ["message"]


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["id", "received_at", "object_type", "status", "attempts", "short_error"]
    list_filter = ["status", "object_type"]
    readonly_fields = ["payload_sha256", "payload", "received_at", "processed_at"]
    actions = ["reprocess"]

    @admin.display(description="Error")
    def short_error(self, obj):
        return obj.error[:80]

    @admin.action(description="Reprocess selected events")
    def reprocess(self, request, queryset):
        results = [processing.process_webhook_event(event) for event in queryset]
        self.message_user(request, f"{sum(results)} processed, {results.count(False)} failed.", messages.INFO)

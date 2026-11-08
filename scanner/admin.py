from django.contrib import admin

from .models import CheckResult, Scan


class CheckResultInline(admin.TabularInline):
    model = CheckResult
    extra = 0
    fields = ("check_id", "status", "label", "priority")
    readonly_fields = fields
    can_delete = False


@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = ("url", "status", "score", "client_ip", "created_at")
    list_filter = ("status",)
    search_fields = ("url",)
    inlines = [CheckResultInline]

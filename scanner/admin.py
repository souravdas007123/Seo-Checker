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
    list_display = ("url", "status", "score", "user", "client_ip", "deep", "created_at")
    list_filter = ("status", "deep")
    search_fields = ("url", "user__username")
    raw_id_fields = ("user",)
    inlines = [CheckResultInline]

import uuid

from django.conf import settings
from django.db import models


class Scan(models.Model):
    QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"
    STATUS_CHOICES = [(s, s) for s in (QUEUED, RUNNING, DONE, FAILED)]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    url = models.URLField(max_length=2000)
    final_url = models.URLField(max_length=2000, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=QUEUED, db_index=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    elapsed_ms = models.PositiveIntegerField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)
    deep = models.BooleanField(default=False)  # poori site crawl
    pages_json = models.TextField(blank=True)  # crawl kiye pages ki list (JSON)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="scans")
    client_ip = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.url} ({self.status}, {self.score})"


class CheckResult(models.Model):
    scan = models.ForeignKey(Scan, on_delete=models.CASCADE, related_name="results")
    check_id = models.CharField(max_length=50)
    category = models.CharField(max_length=20)
    title = models.CharField(max_length=120)
    status = models.CharField(max_length=12)  # pass | warn | fail | info | unverified
    label = models.CharField(max_length=12)  # measured | estimated | unverified
    message = models.TextField(blank=True)
    evidence = models.TextField(blank=True)
    fix = models.TextField(blank=True)
    fix_note = models.TextField(blank=True)
    impact = models.PositiveSmallIntegerField(default=3)
    effort = models.PositiveSmallIntegerField(default=2)
    priority = models.FloatField(default=0)

    class Meta:
        ordering = ["-priority", "check_id"]
        indexes = [models.Index(fields=["scan", "-priority"])]

    def __str__(self):
        return f"{self.check_id}: {self.status}"

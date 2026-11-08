"""Purane scans delete karo (cron/scheduler se roz chalao).

    python manage.py purge_old_scans            # settings ke retention days ke hisaab se
    python manage.py purge_old_scans --dry-run  # sirf ginti, delete nahi
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from scanner.models import Scan


class Command(BaseCommand):
    help = "Retention se purane scans (aur unke results) delete karta hai."

    def add_arguments(self, parser):
        parser.add_argument("--anon-days", type=int, default=None, help="Login ke bina wale scans (default: ANON_RETENTION_DAYS)")
        parser.add_argument("--user-days", type=int, default=None, help="Login user ke scans (default: USER_RETENTION_DAYS)")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        now = timezone.now()
        anon_days = opts["anon_days"] if opts["anon_days"] is not None else settings.ANON_RETENTION_DAYS
        user_days = opts["user_days"] if opts["user_days"] is not None else settings.USER_RETENTION_DAYS
        anon = Scan.objects.filter(user__isnull=True, created_at__lt=now - timedelta(days=anon_days))
        users = Scan.objects.filter(user__isnull=False, created_at__lt=now - timedelta(days=user_days))
        # Atke hue (queued/running) scans jo 1 din se purane hain, user ke ho ya na ho
        stuck = Scan.objects.filter(status__in=[Scan.QUEUED, Scan.RUNNING], created_at__lt=now - timedelta(days=1))
        counts = {"anonymous": anon.count(), "user": users.count(), "stuck": stuck.count()}
        if opts["dry_run"]:
            self.stdout.write(f"[dry-run] delete hote: {counts}")
            return
        for qs in (anon, users, stuck):
            qs.delete()  # CheckResult cascade se hat jaate hain
        self.stdout.write(self.style.SUCCESS(f"Delete hue: {counts}"))

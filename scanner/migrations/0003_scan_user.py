import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('scanner', '0002_scan_deep_scan_pages_json'),
    ]

    operations = [
        migrations.AddField(
            model_name='scan',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='scans', to=settings.AUTH_USER_MODEL),
        ),
    ]

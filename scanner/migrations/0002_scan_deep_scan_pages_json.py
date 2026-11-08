from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scanner', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='scan',
            name='deep',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='scan',
            name='pages_json',
            field=models.TextField(blank=True),
        ),
    ]

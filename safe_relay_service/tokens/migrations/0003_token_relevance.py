# Generated by Django 2.1.3 on 2018-11-09 16:30

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tokens", "0002_auto_20181109_1522"),
    ]

    operations = [
        migrations.AddField(
            model_name="token",
            name="relevance",
            field=models.PositiveIntegerField(default=1),
        ),
    ]

# Generated by Django 3.1.2 on 2020-11-02 16:43

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("relay", "0028_auto_20200922_1000"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ethereumevent",
            name="arguments",
            field=models.JSONField(),
        ),
    ]

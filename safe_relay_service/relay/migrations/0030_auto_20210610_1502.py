# Generated by Django 3.2.4 on 2021-06-10 15:02

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("relay", "0029_auto_20201102_1643"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ethereumevent",
            name="id",
            field=models.BigAutoField(
                auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
            ),
        ),
        migrations.AlterField(
            model_name="safemultisigtx",
            name="id",
            field=models.BigAutoField(
                auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
            ),
        ),
    ]

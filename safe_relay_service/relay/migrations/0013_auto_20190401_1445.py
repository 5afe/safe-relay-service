# Generated by Django 2.1.7 on 2019-04-01 14:45

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("relay", "0012_safemultisigtx_ethereum_tx"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="safemultisigtx",
            name="gas",
        ),
        migrations.RemoveField(
            model_name="safemultisigtx",
            name="tx_hash",
        ),
        migrations.RemoveField(
            model_name="safemultisigtx",
            name="tx_mined",
        ),
    ]

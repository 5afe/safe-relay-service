# Generated by Django 2.0.8 on 2018-10-02 14:22

from django.db import migrations

import gnosis.eth.django.models


class Migration(migrations.Migration):
    dependencies = [
        ("relay", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="safemultisigtx",
            name="refund_receiver",
            field=gnosis.eth.django.models.EthereumAddressField(null=True),
        ),
    ]

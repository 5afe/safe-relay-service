# Generated by Django 2.1.3 on 2018-11-14 12:32

from django.db import migrations

import gnosis.eth.django.models


class Migration(migrations.Migration):
    dependencies = [
        ("relay", "0002_safemultisigtx_refund_receiver"),
    ]

    operations = [
        migrations.AddField(
            model_name="safecreation",
            name="payment_token",
            field=gnosis.eth.django.models.EthereumAddressField(null=True),
        ),
    ]

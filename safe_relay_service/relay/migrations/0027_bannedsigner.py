# Generated by Django 3.0.9 on 2020-09-16 10:53

from django.db import migrations

import gnosis.eth.django.models


class Migration(migrations.Migration):
    dependencies = [
        ("relay", "0026_auto_20200626_1531"),
    ]

    operations = [
        migrations.CreateModel(
            name="BannedSigner",
            fields=[
                (
                    "address",
                    gnosis.eth.django.models.EthereumAddressField(
                        primary_key=True, serialize=False
                    ),
                ),
            ],
        ),
    ]

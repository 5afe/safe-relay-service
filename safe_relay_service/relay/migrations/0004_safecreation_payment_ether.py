# Generated by Django 2.1.3 on 2018-11-16 15:06

from django.db import migrations

import gnosis.eth.django.models


class Migration(migrations.Migration):
    dependencies = [
        ("relay", "0003_safecreation_payment_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="safecreation",
            name="payment_ether",
            field=gnosis.eth.django.models.Uint256Field(default=0),
            preserve_default=False,
        ),
    ]

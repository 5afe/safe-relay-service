# Generated by Django 2.1.7 on 2019-04-01 11:16

from django.db import migrations, models

import gnosis.eth.django.models


def create_ethereum_txs(apps, schema_editor):
    # We can't import the Person model directly as it may be a newer
    # version than this migration expects. We use the historical version.
    SafeMultisigTx = apps.get_model("relay", "SafeMultisigTx")
    EthereumTx = apps.get_model("relay", "EthereumTx")
    for safe_multisig_tx in SafeMultisigTx.objects.all():
        EthereumTx.objects.create(
            tx_hash=safe_multisig_tx.tx_hash,
            _from=None,
            gas=safe_multisig_tx.gas,
            gas_price=0,
            data=safe_multisig_tx.data,
            nonce=0,
            to=safe_multisig_tx.safe.address,
            value=0,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("relay", "0010_ethereumtx"),
    ]

    operations = [
        migrations.RunPython(create_ethereum_txs),
    ]

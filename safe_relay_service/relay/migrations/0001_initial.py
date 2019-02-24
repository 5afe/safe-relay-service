# Generated by Django 2.0.8 on 2018-09-12 12:05

import django.contrib.postgres.fields
import django.db.models.deletion
import django.utils.timezone
import django_eth.models
import model_utils.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='SafeContract',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False,
                                                                verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False,
                                                                      verbose_name='modified')),
                ('address', django_eth.models.EthereumAddressField(primary_key=True, serialize=False)),
                ('master_copy', django_eth.models.EthereumAddressField()),
                ('subscription_module_address', django_eth.models.EthereumAddressField()),
                ('salt', django_eth.models.Uint256Field(unique=True))
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='SafeCreation',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False,
                                                                verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False,
                                                                      verbose_name='modified')),
                ('deployer', django_eth.models.EthereumAddressField(primary_key=True, serialize=False)),
                ('owners',
                 django.contrib.postgres.fields.ArrayField(base_field=django_eth.models.EthereumAddressField(),
                                                           size=None)),
                ('threshold', django_eth.models.Uint256Field()),
                ('payment', django_eth.models.Uint256Field()),
                ('tx_hash', django_eth.models.Sha3HashField(unique=True)),
                ('gas', django_eth.models.Uint256Field()),
                ('gas_price', django_eth.models.Uint256Field()),
                ('value', django_eth.models.Uint256Field()),
                ('v', models.PositiveSmallIntegerField()),
                ('r', django_eth.models.Uint256Field()),
                ('s', django_eth.models.Uint256Field()),
                ('data', models.BinaryField(null=True)),
                ('signed_tx', models.BinaryField(null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='SafeMultisigTx',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False,
                                                                verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False,
                                                                      verbose_name='modified')),
                ('to', django_eth.models.EthereumAddressField(null=True)),
                ('value', django_eth.models.Uint256Field()),
                ('data', models.BinaryField(null=True)),
                ('operation',
                 models.PositiveSmallIntegerField(choices=[(0, 'CALL'), (1, 'DELEGATE_CALL'), (2, 'CREATE')])),
                ('safe_tx_gas', django_eth.models.Uint256Field()),
                ('data_gas', django_eth.models.Uint256Field()),
                ('gas_price', django_eth.models.Uint256Field()),
                ('gas_token', django_eth.models.EthereumAddressField(null=True)),
                ('signatures', models.BinaryField()),
                ('gas', django_eth.models.Uint256Field()),
                ('nonce', django_eth.models.Uint256Field()),
                ('tx_hash', django_eth.models.Sha3HashField(unique=True)),
                ('tx_mined', models.BooleanField(default=False)),
            ],
        ),
        migrations.CreateModel(
            name='SafeMultisigSubTx',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False,
                                                                verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False,
                                                                      verbose_name='modified')),
                ('to', django_eth.models.EthereumAddressField(null=True)),
                ('value', django_eth.models.Uint256Field()),
                ('data', models.BinaryField(null=True)),
                ('period', models.PositiveSmallIntegerField(choices=[
                    (2, 'MINUTE'),
                    (3, 'HOUR'),
                    (4, 'DAY'),
                    (5, 'WEEK'),
                    (6, 'BI_WEEKLY'),
                    (7, 'MONTH'),
                    (8, 'THREE_MONTH'),
                    (9, 'SIX_MONTH'),
                    (10, 'YEAR'),
                    (11, 'TWO_YEAR'),
                    (12, 'THREE_YEAR')
                ])),
                ('start_date', django_eth.models.Uint256Field()),
                ('end_date', django_eth.models.Uint256Field()),
                ('uniq_id', django_eth.models.Uint256Field()),
                ('signatures', models.BinaryField()),
            ],
        ),
        migrations.CreateModel(
            name='SafeFunding',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False,
                                                                verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False,
                                                                      verbose_name='modified')),
                ('safe',
                 models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, serialize=False,
                                      to='relay.SafeContract')),
                ('safe_funded', models.BooleanField(default=False)),
                ('deployer_funded', models.BooleanField(db_index=True, default=False)),
                ('deployer_funded_tx_hash', django_eth.models.Sha3HashField(blank=True, null=True, unique=True)),
                ('safe_deployed', models.BooleanField(db_index=True, default=False)),
                ('safe_deployed_tx_hash', django_eth.models.Sha3HashField(blank=True, null=True, unique=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='safemultisigtx',
            name='safe',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='relay.SafeContract'),
        ),
        migrations.AddField(
            model_name='safemultisigsubtx',
            name='safe',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='relay.SafeContract'),
        ),
        migrations.AddField(
            model_name='safecreation',
            name='safe',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='relay.SafeContract'),
        ),
        migrations.AlterUniqueTogether(
            name='safemultisigtx',
            unique_together={('safe', 'nonce')},
        ),
        migrations.AlterUniqueTogether(
            name='safemultisigsubtx',
            unique_together={('safe', 'signatures')},
        ),
    ]

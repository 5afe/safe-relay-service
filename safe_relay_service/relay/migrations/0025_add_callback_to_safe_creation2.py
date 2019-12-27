from django.db import migrations
import gnosis.eth.django.models



class Migration(migrations.Migration):

    dependencies = [
        ('relay', '0024_add_to_field_to_safe_creation2_20191112_1539'),
    ]

    operations = [
        migrations.AddField(
            model_name='SafeCreation2',
            name='callback',
            field=gnosis.eth.django.models.EthereumAddressField(null=True)
        ),
    ]

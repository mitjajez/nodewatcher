# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('antennas', '0004_auto_20151001_2359'),
    ]

    operations = [
        migrations.AlterField(
            model_name='antennaequipmentconfig',
            name='annotations',
            field=models.TextField(default='{}', editable=False),
        ),
    ]

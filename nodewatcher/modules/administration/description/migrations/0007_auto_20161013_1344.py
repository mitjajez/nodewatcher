# -*- coding: utf-8 -*-
# Generated by Django 1.9.4 on 2016-10-13 11:44
from __future__ import unicode_literals

from django.db import migrations
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('description', '0006_auto_20160206_2118'),
    ]

    operations = [
        migrations.AlterField(
            model_name='descriptionconfig',
            name='annotations',
            field=jsonfield.fields.JSONField(default=dict, editable=False),
        ),
    ]

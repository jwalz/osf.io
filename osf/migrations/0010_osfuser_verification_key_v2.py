# -*- coding: utf-8 -*-
# Generated by Django 1.9 on 2016-10-24 14:37
from __future__ import unicode_literals

from django.db import migrations
import osf.utils.datetime_aware_jsonfield


class Migration(migrations.Migration):

    dependencies = [
        ('osf', '0009_abstractnode_preprint_file'),
    ]

    operations = [
        migrations.AddField(
            model_name='osfuser',
            name='verification_key_v2',
            field=osf.utils.datetime_aware_jsonfield.DateTimeAwareJSONField(blank=True, default=dict),
        ),
    ]

# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-10-26 18:43
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('osf', '0222_auto_20201023_2033'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notificationsubscription',
            name='_id',
            field=models.CharField(db_index=True, max_length=100),
        ),
        migrations.AlterUniqueTogether(
            name='notificationsubscription',
            unique_together=set([('_id', 'provider')]),
        ),
        migrations.AlterUniqueTogether(
            name='notificationsubscription',
            unique_together=set([('_id', 'provider')]),
        ),
    ]

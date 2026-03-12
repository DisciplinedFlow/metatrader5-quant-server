from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0014_add_metals_to_cvd_strategies'),
    ]

    operations = [
        migrations.CreateModel(
            name='RotationLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('session_name', models.CharField(max_length=30)),
                ('regime_state', models.JSONField(default=dict)),
                ('dominant_regime', models.CharField(default='UNKNOWN', max_length=20)),
                ('strategies_scored', models.IntegerField(default=0)),
                ('strategies_activated', models.JSONField(default=list)),
                ('strategies_deactivated', models.JSONField(default=list)),
                ('scores', models.JSONField(default=dict)),
                ('reason', models.TextField(blank=True)),
                ('duration_seconds', models.FloatField(default=0)),
            ],
            options={
                'ordering': ['-timestamp'],
                'indexes': [
                    models.Index(fields=['session_name'], name='nexus_rotat_session_idx'),
                    models.Index(fields=['timestamp'], name='nexus_rotat_timesta_idx'),
                ],
            },
        ),
    ]

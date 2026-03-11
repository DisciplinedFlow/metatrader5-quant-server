"""Add TradeFeature and MLModel for continuous ML learning pipeline."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0012_seed_smc_strategies'),
    ]

    operations = [
        migrations.CreateModel(
            name='TradeFeature',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('features_json', models.JSONField(default=dict)),
                ('ml_score', models.FloatField(blank=True, null=True)),
                ('ml_accepted', models.BooleanField(blank=True, null=True)),
                ('actual_win', models.BooleanField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('trade', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='ml_features',
                    to='nexus.trade',
                )),
            ],
            options={
                'indexes': [
                    models.Index(fields=['actual_win'], name='nexus_trade_actual__idx'),
                    models.Index(fields=['created_at'], name='nexus_trade_created_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='MLModel',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.IntegerField(unique=True)),
                ('model_type', models.CharField(max_length=50)),
                ('trade_count', models.IntegerField()),
                ('accuracy', models.FloatField()),
                ('cv_accuracy', models.FloatField(default=0)),
                ('cv_std', models.FloatField(default=0)),
                ('precision', models.FloatField(default=0)),
                ('recall', models.FloatField(default=0)),
                ('f1_score', models.FloatField(default=0)),
                ('feature_importance', models.JSONField(default=dict)),
                ('learning_curve', models.JSONField(default=list)),
                ('win_rate_baseline', models.FloatField(default=0.5)),
                ('model_path', models.CharField(max_length=200)),
                ('is_active', models.BooleanField(default=False)),
                ('trained_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-version'],
            },
        ),
    ]

"""Add LLM scorer fields to TradeFeature for dual-gate ML pipeline."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0018_enhance_energy_strategies'),
    ]

    operations = [
        migrations.AddField(
            model_name='tradefeature',
            name='llm_decision',
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
        migrations.AddField(
            model_name='tradefeature',
            name='llm_confidence',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tradefeature',
            name='llm_reasoning',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tradefeature',
            name='llm_model',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='tradefeature',
            name='llm_latency_ms',
            field=models.FloatField(blank=True, null=True),
        ),
    ]

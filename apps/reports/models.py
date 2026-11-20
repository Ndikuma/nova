from django.db import models


class GeneratedReport(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'En attente'
        PROCESSING = 'processing', 'En cours'
        COMPLETED = 'completed', 'Terminé'
        FAILED = 'failed', 'Échec'

    report_type = models.CharField(max_length=60)
    parameters = models.JSONField(default=dict, blank=True)
    file = models.FileField(upload_to='reports/%Y/%m/', blank=True)
    file_format = models.CharField(max_length=10, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    file_size = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    completed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(
        'core.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Rapport généré'
        verbose_name_plural = 'Rapports générés'

    def __str__(self):
        when = (
            self.created_at.strftime('%d/%m/%Y %H:%M')
            if self.created_at else 'non généré'
        )
        return f'{self.report_name} · {self.get_status_display()} · {when}'

    @property
    def report_name(self):
        from .documents import REPORT_CATALOG
        return REPORT_CATALOG.get(self.report_type, {}).get('name', self.report_type)

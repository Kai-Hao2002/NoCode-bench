from django.contrib import admin
from .models import EvaluationTask, EvaluationResult

class EvaluationResultInline(admin.StackedInline):
    model = EvaluationResult
    can_delete = False
    verbose_name_plural = 'Result'

@admin.register(EvaluationTask)
class EvaluationTaskAdmin(admin.ModelAdmin):
    list_display = ('nocode_bench_id', 'status', 'start_time', 'end_time', 'celery_task_id')
    list_filter = ('status',)
    search_fields = ('nocode_bench_id',)
    inlines = (EvaluationResultInline,)
    readonly_fields = ('start_time', 'end_time', 'celery_task_id')

# 註：由於 EvaluationResult 是透過 Inline 顯示的，所以不需要單獨註冊。
# 如果您也想單獨訪問它，可以取消註釋下一行：
# admin.site.register(EvaluationResult)

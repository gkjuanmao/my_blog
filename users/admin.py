"""用户模型后台管理（django-unfold）。"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from unfold.admin import ModelAdmin as UnfoldModelAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin, UnfoldModelAdmin):
    """自定义用户后台，默认字段分组基础上展示头像。"""

    fieldsets = list(UserAdmin.fieldsets or []) + [
        ('头像', {'fields': ('avatar', 'avatar_name')}),
    ]

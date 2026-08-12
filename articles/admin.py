"""博客文章后台管理（django-unfold）。"""
from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Article, Category, Tag


@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    """分类后台。"""

    list_display = ['name', 'slug', 'description']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Tag)
class TagAdmin(ModelAdmin):
    """标签后台。"""

    list_display = ['name', 'slug']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Article)
class ArticleAdmin(ModelAdmin):
    """文章后台。"""

    list_display = ['title', 'slug', 'author', 'category', 'is_published', 'publish_time', 'views']
    list_filter = ['is_published', 'category', 'tags']
    search_fields = ['title']
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ['tags']

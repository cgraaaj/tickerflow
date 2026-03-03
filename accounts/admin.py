from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import APIKey, CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(BaseUserAdmin):
    model = CustomUser
    list_display = ("email", "first_name", "last_name", "tier", "balance", "is_active", "is_staff", "created_at")
    list_filter = ("is_active", "is_staff", "tier")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("-created_at",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Plan & Balance", {"fields": ("tier", "balance")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "tier"),
            },
        ),
    )


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ("prefix", "user", "label", "is_active", "created_at", "last_used_at")
    list_filter = ("is_active",)
    search_fields = ("prefix", "user__email", "label")
    readonly_fields = ("id", "prefix", "hashed_key", "created_at", "last_used_at")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

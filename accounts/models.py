import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import CustomUserManager

DEFAULT_BALANCE = Decimal("10000.00")


class CustomUser(AbstractBaseUser, PermissionsMixin):
    """Custom user model using email as the unique identifier."""

    class Tier(models.TextChoices):
        BASIC = "basic", "Basic"
        PRO = "pro", "Pro"
        ENTERPRISE = "enterprise", "Enterprise"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    tier = models.CharField(
        max_length=20,
        choices=Tier.choices,
        default=Tier.BASIC,
    )
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=DEFAULT_BALANCE,
        help_text="Available API credits. Each row returned costs 1 unit.",
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "tickerflow_user"
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.email


class APIKey(models.Model):
    """
    API key with hashed storage. The plaintext key is returned only once
    at creation time. Lookup uses the unhashed prefix for speed, then
    verifies the full SHA-256 hash.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    prefix = models.CharField(max_length=8, db_index=True, editable=False)
    hashed_key = models.CharField(max_length=128, editable=False)
    label = models.CharField(max_length=100, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tickerflow_apikey"
        verbose_name = "API key"
        verbose_name_plural = "API keys"

    def __str__(self):
        return f"{self.prefix}... ({self.user.email})"

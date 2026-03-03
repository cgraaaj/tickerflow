from django.apps import AppConfig


def _ensure_tickerflow_schema(sender, **kwargs):
    """
    Create the 'tickerflow' schema if it doesn't exist.
    Runs before every migrate so tables land in the correct schema on fresh DBs.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("CREATE SCHEMA IF NOT EXISTS tickerflow")


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Accounts & API Keys"

    def ready(self):
        from django.db.models.signals import pre_migrate

        pre_migrate.connect(_ensure_tickerflow_schema, sender=self)

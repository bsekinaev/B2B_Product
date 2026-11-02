"""Разовая проверка доступа и доступных моделей GigaChat API."""

from gigachat import GigaChat

from app.config import Settings


def main() -> int:
    """Запросить список моделей без вывода секретов и токенов."""
    try:
        settings = Settings()
    except Exception as error:
        print(f"GIGACHAT CONFIG: FAIL ({type(error).__name__})")
        return 1

    if settings.gigachat_credentials is None:
        print("GIGACHAT ACCESS: SKIP (credentials not configured)")
        return 2

    credentials = settings.gigachat_credentials.get_secret_value()
    if not credentials:
        print("GIGACHAT ACCESS: SKIP (credentials not configured)")
        return 2

    try:
        with GigaChat(
            credentials=credentials,
            scope=settings.gigachat_scope,
            model=settings.gigachat_model,
            base_url=settings.gigachat_base_url,
            verify_ssl_certs=settings.gigachat_verify_ssl_certs,
            ca_bundle_file=settings.gigachat_ca_bundle_file,
            timeout=settings.gigachat_timeout,
            max_retries=settings.gigachat_max_retries,
        ) as client:
            models = client.get_models()
    except Exception as error:
        print(f"GIGACHAT ACCESS: FAIL ({type(error).__name__})")
        return 1

    print("GIGACHAT ACCESS: PASS")
    print("AVAILABLE MODELS:")
    for model in models.data:
        model_id = getattr(model, "id_", None) or getattr(model, "id", "unknown")
        print(f"- {model_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

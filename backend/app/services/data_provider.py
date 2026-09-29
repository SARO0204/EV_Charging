import os


class DataProviderConfigurationError(RuntimeError):
    pass


def get_data_provider():
    provider_name = os.getenv("GRIDFLOW_DATA_PROVIDER", "firestore").strip().lower()
    if provider_name == "firestore":
        from . import firebase_service

        return firebase_service
    if provider_name == "demo":
        from .demo_data_provider import get_demo_provider

        return get_demo_provider()
    raise DataProviderConfigurationError(
        "GRIDFLOW_DATA_PROVIDER must be either 'firestore' or 'demo'."
    )
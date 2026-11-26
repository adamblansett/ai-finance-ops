from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Tracer

from app.core.config import Settings


def init_telemetry(settings: Settings) -> Tracer:
    """Initialize an OpenTelemetry tracer when OTEL_ENABLED=true, else no-op."""
    if settings.otel_enabled:
        resource = Resource.create({"service.name": settings.app_slug})
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
    return trace.get_tracer(settings.app_slug)

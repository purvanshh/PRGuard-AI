from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from opentelemetry.sdk.trace import TracerProvider
from prguard_ai.observability.tracing import _is_truthy, configure_tracing, get_tracer


def test_is_truthy():
    assert _is_truthy("1") is True
    assert _is_truthy("true") is True
    assert _is_truthy("YES") is True
    assert _is_truthy("on") is True
    assert _is_truthy("0") is False
    assert _is_truthy("false") is False
    assert _is_truthy(None) is False


def test_configure_tracing_offline():
    """Verify configure_tracing returns early in offline mode."""
    with patch("prguard_ai.observability.tracing.settings") as mock_settings:
        mock_settings.prguard_offline_mode = True
        
        with patch("opentelemetry.trace.get_tracer_provider") as mock_get_provider:
            configure_tracing("my-service")
            mock_get_provider.assert_not_called()


def test_configure_tracing_already_configured():
    """Verify configure_tracing returns early if already configured as TracerProvider."""
    with patch("prguard_ai.observability.tracing.settings") as mock_settings:
        mock_settings.prguard_offline_mode = False
        
        mock_provider = MagicMock(spec=TracerProvider)
        with patch("opentelemetry.trace.get_tracer_provider", return_value=mock_provider):
            with patch("opentelemetry.trace.set_tracer_provider") as mock_set_provider:
                configure_tracing("my-service")
                mock_set_provider.assert_not_called()


def test_get_tracer():
    t1 = get_tracer()
    t2 = get_tracer("my-tracer")
    assert t1 is not None
    assert t2 is not None


@patch("prguard_ai.observability.tracing.OTLPSpanExporter")
@patch("prguard_ai.observability.tracing.BatchSpanProcessor")
@patch("prguard_ai.observability.tracing.trace.set_tracer_provider")
def test_configure_tracing_success(mock_set_provider, mock_processor, mock_exporter):
    """Verify configure_tracing successfully configures trace provider."""
    with patch("prguard_ai.observability.tracing.settings") as mock_settings:
        mock_settings.prguard_offline_mode = False
        
        # Mock trace.get_tracer_provider to return something that is NOT TracerProvider
        # so it continues configuration
        with patch("opentelemetry.trace.get_tracer_provider", return_value=None):
            configure_tracing("test-service")
            
            mock_exporter.assert_called_once()
            mock_processor.assert_called_once()
            mock_set_provider.assert_called_once()


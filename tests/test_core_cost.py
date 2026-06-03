"""Tests for core/cost.py module."""

from unittest.mock import MagicMock, Mock

import pytest

from audio_to_subs.core.cost import (
    compute_cost,
    extract_usage,
    CostBreakdown,
)


class TestExtractUsage:
    """Tests for extract_usage function."""

    def test_extract_from_usage_attribute_dict(self) -> None:
        """Test extracting usage from a dict-like usage attribute."""
        mock_response = Mock()
        mock_response.usage = {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "prompt_audio_seconds": 15,
        }
        
        result = extract_usage(mock_response)
        assert result is not None
        assert result["prompt_tokens"] == 10
        assert result["completion_tokens"] == 20
        assert result["prompt_audio_seconds"] == 15

    def test_extract_from_usage_attribute_with_model_dump(self) -> None:
        """Test extracting usage from an object with model_dump."""
        mock_usage = Mock()
        mock_usage.model_dump = Mock(return_value={
            "prompt_tokens": 5,
            "completion_tokens": 10,
            "prompt_audio_seconds": 8,
        })
        mock_response = Mock()
        mock_response.usage = mock_usage
        
        result = extract_usage(mock_response)
        assert result is not None
        assert result["prompt_tokens"] == 5

    def test_extract_from_model_dump_with_usage_key(self) -> None:
        """Test extracting usage from model_dump() output."""
        mock_response = Mock()
        mock_response.model_dump = Mock(return_value={
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "prompt_audio_seconds": 30,
            },
            "text": "test",
        })
        
        result = extract_usage(mock_response)
        assert result is not None
        assert result["prompt_tokens"] == 100

    def test_extract_from_dict_with_usage(self) -> None:
        """Test extracting usage from a plain dict with usage key."""
        mock_response = Mock()
        mock_response.__dict__ = {
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 100,
                "prompt_audio_seconds": 20,
            }
        }
        
        result = extract_usage(mock_response)
        assert result is not None
        assert result["prompt_tokens"] == 50

    def test_extract_no_usage(self) -> None:
        """Test that None is returned when usage is not found."""
        mock_response = Mock()
        mock_response.usage = None
        
        result = extract_usage(mock_response)
        assert result is None

    def test_extract_empty_response(self) -> None:
        """Test extraction from a response with no recognisable usage attribute."""
        # spec=[] ensures the mock has NO attributes at all, so extract_usage
        # cannot find .usage, .model_dump, or __dict__["usage"] and returns None.
        mock_response = Mock(spec=[])

        result = extract_usage(mock_response)
        assert result is None


class TestComputeCost:
    """Tests for compute_cost function."""

    def test_duration_billing_with_usage(self) -> None:
        """Test cost computation with Mistral usage dict."""
        usage = {
            "prompt_audio_seconds": 60,  # 1 minute
        }
        
        result = compute_cost(
            audio_duration_seconds=60.0,
            mistral_usage=usage,
            rate_usd_per_minute=0.5,
        )
        
        assert result.source == "mistral_usage"
        assert result.audio_duration_seconds == 60.0
        assert result.estimated_cost_usd == pytest.approx(0.5)  # 1 minute * $0.50
        assert result.usage == usage

    def test_duration_billing_without_usage(self) -> None:
        """Test cost computation without Mistral usage (fallback)."""
        result = compute_cost(
            audio_duration_seconds=120.0,  # 2 minutes
            mistral_usage=None,
            rate_usd_per_minute=0.5,
        )
        
        assert result.source == "duration_fallback"
        assert result.audio_duration_seconds == 120.0
        assert result.estimated_cost_usd == pytest.approx(1.0)  # 2 minutes * $0.50
        assert result.usage is None

    def test_token_billing(self) -> None:
        """Test token-based billing in addition to duration."""
        usage = {
            "prompt_audio_seconds": 60,
            "prompt_tokens": 100,
            "completion_tokens": 200,
        }
        
        result = compute_cost(
            audio_duration_seconds=60.0,
            mistral_usage=usage,
            rate_usd_per_minute=0.5,
            input_token_rate_usd=0.01,
            output_token_rate_usd=0.02,
        )
        
        # Duration cost: 1 minute * $0.50 = $0.50
        # Token cost: 100 * $0.01 + 200 * $0.02 = $1.00 + $4.00 = $5.00
        # Total: $5.50
        assert result.estimated_cost_usd == pytest.approx(5.50)
        assert result.token_cost_usd == pytest.approx(5.00)

    def test_token_billing_without_rates(self) -> None:
        """Test that token billing is skipped when rates are not provided."""
        usage = {
            "prompt_audio_seconds": 60,
            "prompt_tokens": 100,
            "completion_tokens": 200,
        }
        
        result = compute_cost(
            audio_duration_seconds=60.0,
            mistral_usage=usage,
            rate_usd_per_minute=0.5,
            input_token_rate_usd=None,
            output_token_rate_usd=None,
        )
        
        # Only duration billing
        assert result.estimated_cost_usd == pytest.approx(0.50)
        assert result.token_cost_usd is None

    def test_zero_cost(self) -> None:
        """Test computation with zero rates."""
        result = compute_cost(
            audio_duration_seconds=60.0,
            mistral_usage=None,
            rate_usd_per_minute=0.0,
        )
        
        assert result.estimated_cost_usd == 0.0


class TestCostBreakdown:
    """Tests for CostBreakdown dataclass."""

    def test_creation(self) -> None:
        """Test creating a CostBreakdown instance."""
        breakdown = CostBreakdown(
            audio_duration_seconds=60.0,
            usage={"prompt_audio_seconds": 60},
            estimated_cost_usd=0.5,
            source="mistral_usage",
        )
        
        assert breakdown.audio_duration_seconds == 60.0
        assert breakdown.usage == {"prompt_audio_seconds": 60}
        assert breakdown.estimated_cost_usd == 0.5
        assert breakdown.source == "mistral_usage"
        assert breakdown.token_cost_usd is None

    def test_with_token_cost(self) -> None:
        """Test CostBreakdown with token cost."""
        breakdown = CostBreakdown(
            audio_duration_seconds=60.0,
            usage={"prompt_audio_seconds": 60},
            estimated_cost_usd=1.5,
            source="mistral_usage",
            token_cost_usd=1.0,
        )
        
        assert breakdown.token_cost_usd == 1.0

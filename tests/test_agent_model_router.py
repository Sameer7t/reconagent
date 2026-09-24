"""
Unit & Integration Tests for GeminiModelRouter 9-Tier Cascade & Governance.

Verifies:
1. Classification of errors:
   - Quota limits (429, resource_exhausted, quota, rate limit, 404)
   - Temporary demand spikes (503, unavailable, high demand, timeout)
2. Behavior under Temporary Spikes:
   - Does NOT switch models.
   - Retries on the SAME model using exponential backoff.
3. Behavior under Quota Limits:
   - Strictly cascades to the NEXT model in the 9-tier priority order.
4. Correct sequence of the 9 tiers:
   3.8 Flash -> 3.7 Flash -> 3.6 Flash -> 3.5 Flash -> 3 Flash ->
   2.5 Flash -> 3.5 Flash Lite -> 3.1 Flash Lite -> 2.5 Flash Lite
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pydantic import BaseModel

from agent.router import (
    GeminiModelRouter,
    DEFAULT_MODEL_CASCADE,
    is_quota_limit_error,
    is_temporary_spike_error,
    route_extraction,
)
from agent.state import create_initial_state


class DummyExtractionSchema(BaseModel):
    document_id: str
    total_amount: float



class TestGeminiModelRouter(unittest.TestCase):

    def setUp(self):
        self.state = create_initial_state({
            "invoice_id": "INV-TEST-001",
            "po_id": "PO-TEST-001",
            "vendor_id": "VEND-ACME",
            "status": "DISCREPANCY_DETECTED",
            "discrepancies": [
                {
                    "type": "UNIT_PRICE_MISMATCH",
                    "severity": "CRITICAL",
                    "details": {"invoice_price": "120.00", "po_price": "100.00"}
                }
            ]
        })

    def test_default_cascade_order(self):
        """Verify strict 9-tier cascade order as requested by user."""
        expected = [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3-flash",
            "gemini-2.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
        ]
        self.assertEqual(DEFAULT_MODEL_CASCADE, expected)

    def test_error_classification(self):
        """Verify quota vs spike error detection."""
        # Quota limits
        self.assertTrue(is_quota_limit_error(Exception("429 Resource has been exhausted (e.g. check quota).")))
        self.assertTrue(is_quota_limit_error(Exception("ResourceExhausted: rate limit exceeded")))
        self.assertTrue(is_quota_limit_error(Exception("HTTP 404: models/gemini-3.8-flash is no longer available")))
        self.assertFalse(is_quota_limit_error(Exception("503 Service Unavailable")))

        # Temporary spikes
        self.assertTrue(is_temporary_spike_error(Exception("503 The model is overloaded. Please try again later.")))
        self.assertTrue(is_temporary_spike_error(Exception("Due to high demand, please wait.")))
        self.assertTrue(is_temporary_spike_error(Exception("504 Gateway Timeout")))
        self.assertFalse(is_temporary_spike_error(Exception("429 Resource has been exhausted")))

    @patch("agent.router.time.sleep")
    def test_temporary_spike_does_not_change_model(self, mock_sleep):
        """
        Temporary spike (503) on Tier 1 (3.8 Flash):
        Should retry on 3.8 Flash using exponential backoff, NOT switch to Tier 2.
        If it succeeds on retry 2, tier 1 is used and no cascade occurs.
        """
        router = GeminiModelRouter()
        mock_client = MagicMock()

        # Call 1: 503 spike, Call 2: succeeds on SAME model
        mock_response = MagicMock()
        mock_response.text = '{"action": "investigate", "tool": "get_purchase_order", "parameters": {"po_id": "PO-TEST-001"}, "reasoning": "Verify PO"}'

        invoked_models = []

        def mock_generate_content(model, contents, config):
            invoked_models.append(model)
            if len(invoked_models) == 1:
                raise Exception("503 Service Unavailable due to high demand")
            return mock_response

        mock_client.models.generate_content.side_effect = mock_generate_content

        action = router.route_generation(self.state, client=mock_client)

        self.assertIsNotNone(action)
        self.assertEqual(action.action, "investigate")
        self.assertEqual(action.tool, "get_purchase_order")
        # Both calls were made to Tier 1 ("gemini-3.8-flash")
        self.assertEqual(invoked_models, ["gemini-3.8-flash", "gemini-3.8-flash"])
        # Exponential backoff sleep was called once
        mock_sleep.assert_called_once_with(1.0)

    @patch("agent.router.time.sleep")
    def test_quota_limit_cascades_immediately_to_next_tier(self, mock_sleep):
        """
        Quota limit (429) on Tier 1 (3.8 Flash):
        Should immediately cascade to Tier 2 (3.7 Flash) without retrying Tier 1.
        """
        router = GeminiModelRouter()
        mock_client = MagicMock()

        mock_response = MagicMock()
        mock_response.text = '{"action": "investigate", "tool": "get_purchase_order", "parameters": {"po_id": "PO-TEST-001"}, "reasoning": "Verify PO on tier 2"}'

        invoked_models = []

        def mock_generate_content(model, contents, config):
            invoked_models.append(model)
            if model == "gemini-3.8-flash":
                raise Exception("429 ResourceExhausted: Daily quota exceeded")
            return mock_response

        mock_client.models.generate_content.side_effect = mock_generate_content

        action = router.route_generation(self.state, client=mock_client)

        self.assertIsNotNone(action)
        self.assertEqual(action.action, "investigate")
        # Tier 1 was attempted once (failed with quota), immediately cascaded to Tier 2
        self.assertEqual(invoked_models, ["gemini-3.8-flash", "gemini-3.7-flash"])
        # No backoff delay should be wasted on 429 quota exhaustion
        mock_sleep.assert_not_called()

    @patch("agent.router.time.sleep")
    def test_multi_tier_cascade_to_flash_lite(self, mock_sleep):
        """
        If Tiers 1 through 6 suffer quota limits (429), it must cascade
        down to Tier 7 (3.5 Flash Lite) in strict priority order.
        """
        router = GeminiModelRouter()
        mock_client = MagicMock()

        mock_response = MagicMock()
        mock_response.text = '{"action": "finish", "tool": null, "parameters": {}, "reasoning": "Finished via 3.5 Flash Lite"}'

        invoked_models = []

        def mock_generate_content(model, contents, config):
            invoked_models.append(model)
            if model != "gemini-3.5-flash-lite":
                raise Exception("429 ResourceExhausted: Model quota reached")
            return mock_response

        mock_client.models.generate_content.side_effect = mock_generate_content

        action = router.route_generation(self.state, client=mock_client)

        self.assertIsNotNone(action)
        self.assertEqual(action.action, "finish")
        expected_sequence = [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3-flash",
            "gemini-2.5-flash",
            "gemini-3.5-flash-lite",
        ]
        self.assertEqual(invoked_models, expected_sequence)

    def test_route_structured_extraction_success_tier1(self):
        """Extraction succeeds on Tier 1 (gemini-3.8-flash) using parsed SDK model."""
        router = GeminiModelRouter()
        mock_client = MagicMock()

        expected_doc = DummyExtractionSchema(document_id="DOC-999", total_amount=150.50)
        mock_response = MagicMock()
        mock_response.parsed = expected_doc

        invoked_models = []

        def mock_generate_content(model, contents, config):
            invoked_models.append(model)
            return mock_response

        mock_client.models.generate_content.side_effect = mock_generate_content

        result = router.route_structured_extraction(
            client=mock_client,
            contents=["test prompt"],
            response_schema=DummyExtractionSchema,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.document_id, "DOC-999")
        self.assertEqual(result.total_amount, 150.50)
        self.assertEqual(invoked_models, ["gemini-3.8-flash"])

    @patch("agent.router.time.sleep")
    def test_route_structured_extraction_temporary_spike_backoff(self, mock_sleep):
        """
        Temporary spike (503) during extraction:
        Must NOT switch models. Retries on the SAME model tier using exponential backoff.
        """
        router = GeminiModelRouter()
        mock_client = MagicMock()

        expected_doc = DummyExtractionSchema(document_id="DOC-503", total_amount=88.0)
        mock_response = MagicMock()
        mock_response.parsed = expected_doc

        invoked_models = []

        def mock_generate_content(model, contents, config):
            invoked_models.append(model)
            if len(invoked_models) == 1:
                raise Exception("503 Service Unavailable: High demand on servers")
            return mock_response

        mock_client.models.generate_content.side_effect = mock_generate_content

        result = router.route_structured_extraction(
            client=mock_client,
            contents=["test prompt"],
            response_schema=DummyExtractionSchema,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.document_id, "DOC-503")
        self.assertEqual(invoked_models, ["gemini-3.8-flash", "gemini-3.8-flash"])
        mock_sleep.assert_called_once_with(1.0)

    @patch("agent.router.time.sleep")
    def test_route_structured_extraction_quota_cascades_immediately(self, mock_sleep):
        """
        Quota limit (429) during extraction:
        Must immediately cascade to next model tier in priority order without backoff sleep.
        """
        router = GeminiModelRouter()
        mock_client = MagicMock()

        expected_doc = DummyExtractionSchema(document_id="DOC-429", total_amount=200.0)
        mock_response = MagicMock()
        mock_response.parsed = expected_doc

        invoked_models = []

        def mock_generate_content(model, contents, config):
            invoked_models.append(model)
            if model == "gemini-3.8-flash":
                raise Exception("429 ResourceExhausted: rate limit exceeded")
            return mock_response

        mock_client.models.generate_content.side_effect = mock_generate_content

        result = router.route_structured_extraction(
            client=mock_client,
            contents=["test prompt"],
            response_schema=DummyExtractionSchema,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.document_id, "DOC-429")
        self.assertEqual(invoked_models, ["gemini-3.8-flash", "gemini-3.7-flash"])
        mock_sleep.assert_not_called()

    @patch("agent.router.time.sleep")
    def test_route_extraction_preferred_model_and_quota_cascade(self, mock_sleep):
        """
        route_extraction with preferred_model="gemini-3.5-flash-lite":
        Attempts preferred model first; if 429 quota is hit, cascades to Tier 1, 2, etc.
        """
        mock_client = MagicMock()
        expected_doc = DummyExtractionSchema(document_id="DOC-PREF", total_amount=45.0)
        mock_response = MagicMock()
        mock_response.parsed = expected_doc

        invoked_models = []

        def mock_generate_content(model, contents, config):
            invoked_models.append(model)
            if model == "gemini-3.5-flash-lite":
                raise Exception("429 ResourceExhausted: quota reached")
            return mock_response

        mock_client.models.generate_content.side_effect = mock_generate_content

        result = route_extraction(
            client=mock_client,
            contents=["test prompt"],
            response_schema=DummyExtractionSchema,
            preferred_model="gemini-3.5-flash-lite",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.document_id, "DOC-PREF")
        # Started with preferred model, then cascaded to Tier 1 ("gemini-3.8-flash")
        self.assertEqual(invoked_models, ["gemini-3.5-flash-lite", "gemini-3.8-flash"])
        mock_sleep.assert_not_called()

    def test_route_structured_extraction_fallback_json_deserializer(self):
        """
        If response.parsed is None, fallback to JSON parsing of response.text into response_schema.
        """
        router = GeminiModelRouter()
        mock_client = MagicMock()

        mock_response = MagicMock()
        mock_response.parsed = None
        mock_response.text = '{"document_id": "DOC-TEXT", "total_amount": 99.99}'

        mock_client.models.generate_content.return_value = mock_response

        result = router.route_structured_extraction(
            client=mock_client,
            contents=["test prompt"],
            response_schema=DummyExtractionSchema,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.document_id, "DOC-TEXT")
        self.assertEqual(result.total_amount, 99.99)



if __name__ == "__main__":
    print("\n============================================================")
    print("RUNNING GEMINI MODEL ROUTER & CASCADE GOVERNANCE TEST SUITE")
    print("============================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestGeminiModelRouter)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("============================================================")
        print("ALL GEMINI MODEL ROUTER TESTS PASSED!")
        print("============================================================\n")
    else:
        sys.exit(1)


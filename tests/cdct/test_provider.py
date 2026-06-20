"""
CDCT — Provider-side Pact verification.

Consumers that must publish contracts:
  - vite-ews-frontend   → verifies HTTP /outliers, /denoise, /regression, /predict
  - early-warning-service → verifies gRPC DetectOutliers (report enrichment path)

Run locally:
    PACT_BROKER_URL=http://localhost:9292 pytest tests/cdct -v

In CI the PACT_BROKER_URL and PACT_BROKER_TOKEN secrets are set via GitHub Actions.
"""
import os
import threading

import pytest
import uvicorn

from app.http_app import create_app

# ── Provider HTTP server fixture ──────────────────────────────────────────────

PROVIDER_HOST = "127.0.0.1"
PROVIDER_PORT = 18090


@pytest.fixture(scope="module", autouse=True)
def provider_server():
    """Start the FastAPI app on a fixed port for Pact to call."""
    app = create_app()
    config = uvicorn.Config(app, host=PROVIDER_HOST, port=PROVIDER_PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    import time
    import requests
    for _ in range(20):
        try:
            requests.get(f"http://{PROVIDER_HOST}:{PROVIDER_PORT}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.3)

    yield
    server.should_exit = True


# ── HTTP contract verification (vite-ews-frontend consumer) ──────────────────

def test_http_pacts_from_broker():
    """Verify all HTTP pacts published by vite-ews-frontend against this provider."""
    broker_url = os.environ.get("PACT_BROKER_URL", "")
    if not broker_url:
        pytest.skip("PACT_BROKER_URL not set — skipping broker verification")

    from pact import Verifier

    verifier = Verifier(
        provider="data-analysis",
        provider_base_url=f"http://{PROVIDER_HOST}:{PROVIDER_PORT}",
    )

    output, _ = verifier.verify_with_broker(
        broker_url=broker_url,
        broker_token=os.environ.get("PACT_BROKER_TOKEN", ""),
        consumer_selectors=[{"consumer": "vite-ews-frontend", "latest": True}],
        publish_verification_results=os.environ.get("CI") == "true",
        provider_version=os.environ.get("GITHUB_SHA", "local"),
    )
    assert output == 0, "One or more HTTP pact interactions failed verification"


# ── Local pact file fallback (no broker needed for local dev) ─────────────────

def test_http_pacts_from_file(tmp_path):
    """
    Verify against a local pact file if present at tests/cdct/pacts/.
    Useful for running verification before pushing to the broker.
    """
    pact_dir = os.path.join(os.path.dirname(__file__), "pacts")
    if not os.path.isdir(pact_dir) or not os.listdir(pact_dir):
        pytest.skip("No local pact files found in tests/cdct/pacts/")

    from pact import Verifier

    verifier = Verifier(
        provider="data-analysis",
        provider_base_url=f"http://{PROVIDER_HOST}:{PROVIDER_PORT}",
    )
    output, _ = verifier.verify_pacts(sources=[pact_dir])
    assert output == 0, "One or more local pact interactions failed verification"

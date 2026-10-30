# Payment Workflow Test Harness

A deterministic Python test harness for exercising the payment-to-ledger workflow without depending on live Polyhedron services. It has two test boundaries: an in-memory fake for fast business-flow tests and a local HTTP mock for exercising the actual HTTP client contract and retry behavior.

## Harness infrastructure

| Component | Purpose |
| --- | --- |
| `payments.json` | Sample confirmed-payment input consumed by the workflow. |
| `fixtures/cases.json` | Table-driven payment, bill, expected-write, and expected-message scenarios. |
| `tests/test_workflow.py` | Pytest scenarios; uses `FakePolyhedron` for fast tests and `MockPolyhedronServer` for HTTP integration tests. |
| `__init__.py` | Workflow under test: reads payments, retrieves bills, checks current eligibility rules, and writes ledger entries. |
| `polyhedron_client.py` | HTTP adapter for bills and ledger endpoints; applies timeouts and bounded retries. |
| `mock_polyhedron_server.py` | Local threaded HTTP server implementing the client endpoints and configurable failure responses. |
| `requirements-test.txt` / `Pipfile` | Test and runtime dependencies. |
| `Makefile` | Convenience targets for dependency setup, running the workflow, and generating the HTML test report. |

The fast tests patch the HTTP client with an in-memory fake and make no network calls. HTTP integration tests exercise the real client against the local mock. The mock binds to `127.0.0.1` by default and does not require credentials or external services.

## Step-by-step: install and run tests

1. Install Python 3.13 and `pipenv`, or use an existing Python environment. From the repository directory, create/activate that environment as appropriate.
2. Install the project test dependencies using one of these supported approaches:

	 ```bash
	 python -m pip install -r requirements-test.txt
	 ```

	 Or use the Pipenv setup:

	 ```bash
	 make build
	 ```

3. Run the tests:

	 ```bash
	 python -m pytest -v tests/
	 ```

4. Generate the self-contained HTML report:

	 ```bash
	 make test
	 ```

	 Open `test-report.html` in a browser to review pass/fail results. The report is generated locally and may contain test names and failure details; review it before sharing.

## Step-by-step: run the local HTTP mock

1. Start the server in a terminal from the repository directory:

	 ```bash
	 python mock_polyhedron_server.py --host 127.0.0.1 --port 8089
	 ```

	 It prints the API base URL, normally `http://127.0.0.1:8089/api`. The server binds to loopback by default; keep that default unless access from a controlled isolated test network is specifically needed.

2. In another terminal, point the workflow at the mock and provide dummy credentials:

	 ```bash
	 POLYHEDRON_BASE_URL=http://127.0.0.1:8089/api \
	 POLYHEDRON_USERNAME=mock-user \
	 POLYHEDRON_PASSWORD=mock-password \
	 PAYMENTS_FILEPATH=./payments.json \
	 python __init__.py
	 ```

3. Stop the server with Ctrl+C when finished. The server exposes `GET /api/bills/{payment_id}`, `POST /api/ledger/entries`, and `GET /health`.

For configured mock responses, pass a JSON file using `--config`. Example structure:

```json
{
	"bills_by_payment": {
		"poly_payment_1": [
			{"bill_id": "bill_wages_1", "balance": 65553.21}
		]
	},
	"bill_actions": {
		"poly_payment_1": [
			{"type": "status", "status": 500}
		]
	},
	"ledger_actions": []
}
```

Actions are consumed in order. `{"type":"status","status":500}` returns a simulated server error; `{"type":"timeout","seconds":2}` delays the response. For example, a queued 500 followed by no further action lets the client demonstrate a transient failure followed by a successful retry. If delay exceeds the client timeout, the client retries according to its configured policy.

## Failure behavior and safety

- The HTTP client defaults to a 5-second timeout and two retries for GET requests on connection/timeouts and HTTP 500/502/503/504 responses.
- Ledger POST retries are disabled by default to avoid duplicate writes. Enable `retry_writes=True` only for an API that guarantees idempotency; the workflow currently does not configure this option.
- The mock has no authentication enforcement; it records request headers to support test assertions. Never put real credentials in fixture files.
- The `POLYHEDRON_BASE_URL` override allows pointing the harness to a compatible staging service. Confirm authorization, test data, and write-safety with the service owner before using staging. Prefer the local mock for fault injection.
- These tests document current behavior rather than asserting the workflow is production-ready. Known gaps include multi-bill allocation, payment/bill amount matching, duplicate-payment handling, and decimal-safe money arithmetic.

## Useful commands

| Goal | Command |
| --- | --- |
| Install with pip | `python -m pip install -r requirements-test.txt` |
| Run tests | `python -m pytest -v tests/` |
| Run tests and generate report | `make test` |
| Start local HTTP mock | `python mock_polyhedron_server.py --port 8089` |
| Run workflow against configured URL | `POLYHEDRON_BASE_URL=http://127.0.0.1:8089/api python __init__.py` |

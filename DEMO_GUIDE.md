# Nivelo / Polyhedron deterministic test harness

For complete infrastructure descriptions and step-by-step setup, test, mock-server, and report instructions, see [README.md](README.md).

## Run

```bash
python -m pip install -r requirements-test.txt
python -m pytest -v tests/
```

To run the tests and create a self-contained HTML report, run `make test`. The report is written to `test-report.html`.

## Design

The provided workflow is imported unchanged. A fake PolyhedronClient is injected at the external dependency boundary. It returns fixture-defined bills, captures attempted ledger writes, and never sends HTTP requests. A fresh fake is constructed for each test, so test cases are independent and repeatable. Each fixture declares the payment, bills, simulated write response, expected write count and expected log message.


## Local HTTP mock

`mock_polyhedron_server.py` implements the `/api/bills/{payment_id}` and `/api/ledger/entries` endpoints and binds to loopback by default. Run it with `python mock_polyhedron_server.py --port 8089`, then set `POLYHEDRON_BASE_URL=http://127.0.0.1:8089/api` to point the workflow at it (or at a compatible staging API). A JSON file supplied with `--config` can define `bills_by_payment`, `bill_actions`, and `ledger_actions`; queued actions can return an HTTP status or delay a response to simulate transient failures. Keep the mock bound to loopback unless there is a specific isolated-network need.

The client uses a finite request timeout and retries GET requests for transient network failures and HTTP 500/502/503/504 responses. POST retries are disabled by default to avoid duplicate ledger writes; enable `retry_writes=True` only when the target API guarantees idempotent writes.

## Notes / known gaps

- This is a **test harness** around the supplied code, not a production-ready implementation of multi-bill allocation.
- The provided sample has one payment and no actual bank event transport; the test treats payment JSON as the confirmed-payment input.
- FakePolyhedron is in-memory and is reset between cases. If staging requires a persistent mock HTTP service, the same fixtures can back a local stub server.
- The supplied workflow uses `float` for money; production payment calculations should use decimal-safe arithmetic.
- The workflow does not currently validate payment amount against bill balance or deduplicate confirmations.

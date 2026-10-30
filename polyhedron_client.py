import json
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from type_utils import PolyhedronBill, PolyhedronCreateLedgerEntry


class PolyhedronClient:
    username: str
    password: str
    base_url: str

    def __init__(
        self,
        username: str,
        password: str,
        base_url="https://polyhedron.cl/api",
        timeout: float = 5.0,
        max_retries: int = 2,
        retry_writes: bool = False,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        retry_methods = {"GET"}
        if retry_writes:
            # Only enable this when the upstream ledger endpoint is idempotent.
            retry_methods.add("POST")
        retry = Retry(
            total=max_retries,
            connect=max_retries,
            read=max_retries,
            status=max_retries,
            backoff_factor=0.1,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset(retry_methods),
            raise_on_status=False,
            respect_retry_after_header=False,
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def get_bills(self, payment_id: str) -> List[PolyhedronBill]:
        resp = self.session.get(
            f"{self.base_url}/bills/{payment_id}",
            headers={"username": self.username, "password": self.password},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def write_to_ledger(self, payment_id: str, ledger_entry: PolyhedronCreateLedgerEntry) -> bool:
        resp = self.session.post(
            f"{self.base_url}/ledger/entries",
            headers={"username": self.username, "password": self.password},
            data=json.dumps({"payment_id": payment_id, "entries": ledger_entry}),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.text == "true"

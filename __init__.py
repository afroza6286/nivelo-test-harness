from datetime import datetime
import json
import os
import sys
from typing import Any, List, Union

from polyhedron_client import PolyhedronClient
from type_utils import Payment, PolyhedronBill, PolyhedronCreateLedgerEntry


def validate_eligibility(bills: List[PolyhedronBill]) -> Union[str, None]:
    if len(bills) == 0:
        return "Payment has no bills!"
    if len(bills) > 1:
        return "Payment has too many bills!"
    bill = bills[0]
    if bill["balance"] == 0:
        return "Bill has no open balance!"
    if bill["balance"] < 0:
        return "Bill has negative balance!"
    return None


def map_transactions_to_ledger_entry(payment: Payment, bill: PolyhedronBill) -> PolyhedronCreateLedgerEntry:
    return {
        "bill_id": bill["bill_id"],
        "deposit_amount": payment["payment_amount"],
        "deposit_date": payment["payment_date"].isoformat(),
        "deposit_description": f"Payment for client {payment['client_code']}",
    }


def load_payments(file_path: str) -> List[Payment]:
    payments: List[Payment] = []
    with open(file_path, "r") as payment_file:
        data = json.load(payment_file)
        for row in data:
            payments.append(
                {
                    "payment_id": row["payment_id"],
                    "payment_external_id": row["payment_external_id"],
                    "payment_date": datetime.strptime(row["payment_date"], "%Y-%m-%d"),
                    "payment_amount": row["payment_amount"],
                    "client_code": row["client_code"],
                }
            )
    return payments


def main():
    polyhedron_username = os.getenv("POLYHEDRON_USERNAME")
    polyhedron_password = os.getenv("POLYHEDRON_PASSWORD")
    polyhedron_base_url = os.getenv("POLYHEDRON_BASE_URL", "https://polyhedron.cl/api")
    payment_file_path = os.getenv("PAYMENTS_FILEPATH", "./payments.json")
    poly_client = PolyhedronClient(polyhedron_username, polyhedron_password, polyhedron_base_url)
    payments = load_payments(payment_file_path)
    for payment in payments:
        poly_payment_id = payment["payment_external_id"]
        bills = poly_client.get_bills(poly_payment_id)
        eligibility_error = validate_eligibility(bills)
        if eligibility_error:
            print(f"Unable to process payment {payment['payment_id']}: {eligibility_error}", file=sys.stderr)
            continue
        ledger_entry = map_transactions_to_ledger_entry(payment, bills[0])
        resp = poly_client.write_to_ledger(poly_payment_id, ledger_entry)
        if not resp:
            print(f"Failed to write payment ${poly_payment_id} to ledger")
        else:
            print(f"Wrote payment {poly_payment_id} to ledger")


if __name__ == "__main__":
    main()

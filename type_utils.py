from datetime import date
from typing import TypedDict


class Payment(TypedDict):
    payment_id: str
    payment_external_id: str
    payment_date: date
    payment_amount: float
    client_code: str


class PolyhedronBill(TypedDict):
    bill_id: str
    balance: float


class PolyhedronCreateLedgerEntry(TypedDict):
    bill_id: str
    deposit_amount: float
    deposit_date: str
    deposit_description: str

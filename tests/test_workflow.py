import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import pytest
import importlib.util
import requests

from mock_polyhedron_server import MockPolyhedronServer, MockPolyhedronState
from polyhedron_client import PolyhedronClient

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('workflow', ROOT / '__init__.py')
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)
CASES = json.loads((ROOT / 'fixtures' / 'cases.json').read_text())

class FakePolyhedron:
    def __init__(self, bills, write_result=True):
        self.bills = bills
        self.write_result = write_result
        self.writes = []
        self.requests = []
    def get_bills(self, payment_id):
        self.requests.append(payment_id)
        return self.bills
    def write_to_ledger(self, payment_id, ledger_entry):
        self.writes.append({'payment_id': payment_id, 'entry': ledger_entry})
        return self.write_result

@pytest.mark.parametrize('case', CASES, ids=lambda c:c['id'])
def test_workflow_scenarios(case, tmp_path, capsys):
    path = tmp_path / 'payments.json'
    path.write_text(json.dumps([case['payment']]))
    fake = FakePolyhedron(case['bills'], case.get('write_result', True))
    with patch.object(workflow, 'PolyhedronClient', return_value=fake), patch.dict('os.environ', {'PAYMENTS_FILEPATH':str(path)}):
        workflow.main()
    assert len(fake.writes) == case['expected_writes']
    assert fake.requests == [case['payment']['payment_external_id']]
    if case['expected_writes']:
        entry = fake.writes[0]['entry']
        assert entry == {
            'bill_id':case['bills'][0]['bill_id'],
            'deposit_amount':case['payment']['payment_amount'],
            'deposit_date':case['payment']['payment_date'] + 'T00:00:00',
            'deposit_description':f"Payment for client {case['payment']['client_code']}"
        }
    output = capsys.readouterr()
    assert case['expected_message'] in output.out + output.err

@pytest.mark.parametrize('bills,expected', [
    ([], 'Payment has no bills!'),
    ([{'bill_id':'b1','balance':1},{'bill_id':'b2','balance':2}], 'Payment has too many bills!'),
    ([{'bill_id':'b1','balance':0}], 'Bill has no open balance!'),
    ([{'bill_id':'b1','balance':-1}], 'Bill has negative balance!'),
    ([{'bill_id':'b1','balance':10}], None),
])
def test_eligibility_rules(bills,expected):
    assert workflow.validate_eligibility(bills) == expected

def test_load_payments_date(tmp_path):
    path=tmp_path/'payments.json'
    path.write_text(json.dumps([CASES[0]['payment']]))
    loaded=workflow.load_payments(str(path))
    assert loaded[0]['payment_date'].date().isoformat() == '2026-01-01'

def test_invalid_date_is_rejected(tmp_path):
    bad=dict(CASES[0]['payment'],payment_date='2026-99-99')
    path=tmp_path/'payments.json'
    path.write_text(json.dumps([bad]))
    with pytest.raises(ValueError):
        workflow.load_payments(str(path))

def test_supplied_payments_file_is_processed(tmp_path, capsys):
    payment_file = ROOT / 'payments.json'
    payment = json.loads(payment_file.read_text())[0]
    fake = FakePolyhedron([{'bill_id': 'bill_wages_1', 'balance': payment['payment_amount']}])
    with patch.object(workflow, 'PolyhedronClient', return_value=fake), patch.dict(
        'os.environ', {'PAYMENTS_FILEPATH': str(payment_file)}
    ):
        workflow.main()
    assert fake.requests == [payment['payment_external_id']]
    assert fake.writes == [{
        'payment_id': payment['payment_external_id'],
        'entry': {
            'bill_id': 'bill_wages_1',
            'deposit_amount': payment['payment_amount'],
            'deposit_date': payment['payment_date'] + 'T00:00:00',
            'deposit_description': f"Payment for client {payment['client_code']}",
        },
    }]
    assert f"Wrote payment {payment['payment_external_id']} to ledger" in capsys.readouterr().out

def test_workflow_processes_multiple_payments(tmp_path):
    first = dict(CASES[0]['payment'])
    second = dict(first, payment_id='payment_second', payment_external_id='poly_payment_second')
    path = tmp_path / 'payments.json'
    path.write_text(json.dumps([first, second]))
    fake = FakePolyhedron([{'bill_id': 'bill_shared', 'balance': first['payment_amount']}])
    with patch.object(workflow, 'PolyhedronClient', return_value=fake), patch.dict(
        'os.environ', {'PAYMENTS_FILEPATH': str(path)}
    ):
        workflow.main()
    assert fake.requests == [first['payment_external_id'], second['payment_external_id']]
    assert [write['payment_id'] for write in fake.writes] == fake.requests

def test_empty_payments_file_makes_no_polyhedron_requests(tmp_path):
    path = tmp_path / 'payments.json'
    path.write_text('[]')
    fake = FakePolyhedron([])
    with patch.object(workflow, 'PolyhedronClient', return_value=fake), patch.dict(
        'os.environ', {'PAYMENTS_FILEPATH': str(path)}
    ):
        workflow.main()
    assert fake.requests == []
    assert fake.writes == []

def test_http_client_uses_mock_api_contract():
    payment_id = 'poly_payment_http'
    bills = [{'bill_id': 'bill_http', 'balance': 42.5}]
    state = MockPolyhedronState(bills_by_payment={payment_id: bills})
    with MockPolyhedronServer(state) as server:
        client = PolyhedronClient('test-user', 'test-password', server.base_url)
        assert client.get_bills(payment_id) == bills
        assert client.write_to_ledger(payment_id, {'bill_id': 'bill_http', 'deposit_amount': 42.5})
    assert [entry['method'] for entry in state.requests] == ['GET', 'POST']
    assert state.ledger_entries == [{
        'payment_id': payment_id,
        'entries': {'bill_id': 'bill_http', 'deposit_amount': 42.5},
    }]
    assert state.requests[0]['headers']['username'] == 'test-user'
    assert state.requests[0]['headers']['password'] == 'test-password'

def test_workflow_can_target_mock_http_server(capsys):
    payment = json.loads((ROOT / 'payments.json').read_text())[0]
    bills = [{'bill_id': 'bill_workflow_http', 'balance': payment['payment_amount']}]
    state = MockPolyhedronState(bills_by_payment={payment['payment_external_id']: bills})
    with MockPolyhedronServer(state) as server, patch.dict(
        'os.environ',
        {
            'PAYMENTS_FILEPATH': str(ROOT / 'payments.json'),
            'POLYHEDRON_BASE_URL': server.base_url,
            'POLYHEDRON_USERNAME': 'mock-user',
            'POLYHEDRON_PASSWORD': 'mock-password',
        },
    ):
        workflow.main()
    assert len(state.ledger_entries) == 1
    assert state.ledger_entries[0]['payment_id'] == payment['payment_external_id']
    assert f"Wrote payment {payment['payment_external_id']} to ledger" in capsys.readouterr().out

def test_http_client_retries_transient_500_for_bill_lookup():
    payment_id = 'poly_payment_500'
    bills = [{'bill_id': 'bill_after_retry', 'balance': 10}]
    state = MockPolyhedronState(
        bills_by_payment={payment_id: bills},
        bill_actions={payment_id: [{'type': 'status', 'status': 500}]},
    )
    with MockPolyhedronServer(state) as server:
        client = PolyhedronClient('user', 'password', server.base_url, max_retries=1)
        assert client.get_bills(payment_id) == bills
    assert len(state.requests) == 2

def test_http_client_retries_after_bill_lookup_timeout():
    payment_id = 'poly_payment_timeout'
    bills = [{'bill_id': 'bill_after_timeout', 'balance': 10}]
    state = MockPolyhedronState(
        bills_by_payment={payment_id: bills},
        bill_actions={payment_id: [{'type': 'timeout', 'seconds': 0.1}]},
    )
    with MockPolyhedronServer(state) as server:
        client = PolyhedronClient('user', 'password', server.base_url, timeout=0.02, max_retries=1)
        assert client.get_bills(payment_id) == bills
    assert len(state.requests) == 2

def test_http_500_ledger_failure_is_not_retried_by_default():
    state = MockPolyhedronState(ledger_actions=[{'type': 'status', 'status': 500}])
    with MockPolyhedronServer(state) as server:
        client = PolyhedronClient('user', 'password', server.base_url, max_retries=2)
        with pytest.raises(requests.HTTPError):
            client.write_to_ledger('poly_payment_ledger', {'bill_id': 'bill_ledger'})
    assert len(state.requests) == 1
    assert state.ledger_entries == []

def test_ledger_retries_are_opt_in_for_idempotent_upstreams():
    state = MockPolyhedronState(ledger_actions=[{'type': 'status', 'status': 500}])
    with MockPolyhedronServer(state) as server:
        client = PolyhedronClient(
            'user', 'password', server.base_url, max_retries=1, retry_writes=True
        )
        assert client.write_to_ledger('poly_payment_safe_retry', {'bill_id': 'bill_safe'})
    assert len(state.requests) == 2
    assert len(state.ledger_entries) == 1

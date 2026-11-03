"""Extend the verified mechanical transport with explicit feature commands."""
from contextlib import contextmanager
from unittest.mock import patch
import module_test_transport_v1 as base

ORIGINAL=base.admit
ACTIONS=base.ACTIONS|{'module','battle','service'}
SERVICES={'press_scan','press_solve','press_daily'}
Commands=base.Commands

def admit(command,receipt):
    action=command.get('action')
    if action not in {'module','battle','service'}:return ORIGINAL(command,receipt)
    row=ORIGINAL(dict(command,action='wait'),receipt);row['action']=action
    if action=='service' and row.get('service') not in SERVICES:
        raise ValueError('explicit supported feature service required')
    if action=='battle' and (not isinstance(row.get('job'),str) or not row['job'].endswith('.json')):
        raise ValueError('explicit checked local mission job required')
    return row

@contextmanager
def boundary():
    with patch.object(base,'admit',admit):yield

def submit(output,command):
    with boundary():return base.submit(output,command)

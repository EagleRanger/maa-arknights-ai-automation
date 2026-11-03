"""V1 native mastery with the real home OCR variant repaired at its consumer."""
from contextlib import contextmanager
from unittest.mock import patch
import operator_training_v1 as previous
from operator_home_labels_v1 import boundary as home,observe_account

BASE_SERVICE=previous.service

def service(app,**kwargs):
    kwargs.setdefault('observer',observe_account)
    with home(app):return BASE_SERVICE(app,**kwargs)

@contextmanager
def boundary(app):
    with patch.object(previous,'service',service),previous.boundary(app):yield

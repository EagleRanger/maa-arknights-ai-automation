"""Normalize the observed COMPLETE accent error, preserve V1 action rules."""
import unicodedata
from unittest.mock import patch
import annihilation_postclear_v1 as previous

ORIGINAL_REWARDS = previous.rewards


def rewards(rows):
    normalized=[]
    for text,x,y in rows:
        plain=''.join(c for c in unicodedata.normalize('NFKD',str(text)) if not unicodedata.combining(c))
        # Only the exact row-state word is normalized, not arbitrary Chinese
        # content, counters, stage identity or claim targets.
        normalized.append(('COMPLETE' if plain.upper()=='COMPLETE' else text,x,y))
    return ORIGINAL_REWARDS(normalized)


def service(*args,**kwargs):
    with patch.object(previous,'rewards',rewards):return previous.service(*args,**kwargs)

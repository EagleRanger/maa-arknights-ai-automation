"""Portable account facts -> decision -> verified feedback, with no game I/O.

The caller verifies game semantics. This store scopes and preserves the evidence;
it never ships somebody's completion state or creates game goals/permissions.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import shutil


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def uid_from_items(items):
    # UID is on the left of the normal home, not a currency/date/level number.
    rows = [re.sub(r'\s+', '', str(t)).upper() for t, x, y in items
            if 0 <= x <= 500 and 560 <= y <= 720]
    hits = {m for value in rows for m in re.findall(r'(?:UID|ID)[:：]?(\d{6,12})(?!\d)', value)}
    return next(iter(hits)) if len(hits) == 1 else None


def account(client, uid):
    if not isinstance(client, str) or not client.strip() or not re.fullmatch(r'\d{6,12}', str(uid)):
        raise ValueError('verified client/server and numeric game UID required')
    return dict(client=client, uid=str(uid))


class AccountProgress:
    def __init__(self, data_root, identity):
        self.identity = account(identity.get('client'), identity.get('uid'))
        key = hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode()).hexdigest()[:24]
        self.folder = Path(data_root) / key
        self.path = self.folder / 'actual_state.json'

    def read(self):
        if not self.path.exists():
            return dict(schema_version=1, account=self.identity, facts={})
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if data.get('account') != self.identity or data.get('schema_version') != 1:
            raise ValueError('account state identity/schema mismatch')
        return data

    def write(self, data):
        self.folder.mkdir(parents=True, exist_ok=True)
        data['updated_at'] = now()
        temp = self.path.with_suffix('.json.tmp')
        with temp.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, self.path)

    @staticmethod
    def key(theme, capability, revision):
        if any(not isinstance(v, str) or not v.strip() for v in (theme, capability, revision)):
            raise ValueError('theme, capability and game-tree revision required')
        return json.dumps([theme, capability, revision], ensure_ascii=False, separators=(',', ':'))

    def evidence(self, paths):
        paths = list(dict.fromkeys(str(Path(p).resolve()) for p in paths))
        if not paths or len(paths) > 6:
            raise ValueError('1..6 verified local evidence files required')
        result = []
        for raw in paths:
            source = Path(raw)
            if not source.is_file() or not 1 < source.stat().st_size <= 16 * 1024 * 1024:
                raise ValueError('invalid/oversized evidence file')
            sha = digest(source)
            relative = 'evidence/' + sha + source.suffix.lower()
            target = self.folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)
            if digest(target) != sha:
                raise ValueError('account evidence copy mismatch')
            result.append(dict(path=relative, sha256=sha))
        return result

    def remember_verified(self, *, theme, capability, revision, progress, total,
                          terminal_verified, run_id, evidence, identity_evidence):
        if (type(progress) is not int or type(total) is not int or not 0 <= progress <= total
                or total <= 0 or type(terminal_verified) is not bool or not run_id
                or terminal_verified != (progress == total)):
            raise ValueError('actual progress and matching verified terminal required')
        key = self.key(theme, capability, revision)
        data = self.read()
        proof = self.evidence(evidence)
        identity_proof = self.evidence(identity_evidence)
        data['identity_evidence'] = identity_proof
        data['facts'][key] = dict(theme=theme, capability=capability, revision=revision,
            status='verified_complete' if terminal_verified else 'verified_partial',
            progress=progress, total=total,
            observed_at=now(), source_run_id=run_id, evidence=proof)
        self.write(data)
        return data['facts'][key]

    def remember_complete(self, **kwargs):
        if kwargs.get('terminal_verified') is not True:
            raise ValueError('verified full terminal required')
        return self.remember_verified(**kwargs)

    def decision(self, *, theme, capability, revision):
        key = self.key(theme, capability, revision)
        base = dict(account=self.identity, theme=theme, capability=capability, revision=revision,
                    action='inspect', reason='no_verified_completion', source=str(self.path), game_actions=0)
        try:
            data = self.read()
            row = data['facts'].get(key) or {}
            if (row.get('status') not in {'verified_complete','verified_partial'}
                    or type(row.get('total')) is not int or type(row.get('progress')) is not int
                    or not 0 <= row['progress'] <= row['total'] or row['total'] <= 0):
                return base
            if (row['status'] == 'verified_complete') != (row['progress'] == row['total']):
                return base
            proofs = (data.get('identity_evidence') or []) + (row.get('evidence') or [])
            if len(proofs) < 2:
                return dict(base, reason='completion_evidence_missing')
            for proof in proofs:
                path = (self.folder / proof['path']).resolve()
                path.relative_to(self.folder.resolve())
                if digest(path) != proof['sha256']:
                    return dict(base, reason='completion_evidence_changed')
            if row['status'] == 'verified_partial':
                return dict(base, reason='verified_partial_requires_current_inspection', fact=row)
            return dict(base, action='skip_permanent_complete', reason='verified_account_completion',
                        fact=row)
        except (OSError, ValueError, KeyError, TypeError):
            return dict(base, reason='account_fact_unusable_reinspect')

    def invalidate(self, *, theme, capability, revision, reason):
        data = self.read()
        row = data['facts'].get(self.key(theme, capability, revision))
        if row:
            row.update(status='invalidated', invalidated_at=now(), invalidation_reason=reason)
            self.write(data)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Read this account progress and derived next action; no game control')
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--client', required=True)
    parser.add_argument('--uid', required=True)
    parser.add_argument('--theme', required=True)
    parser.add_argument('--capability', default='permanent_growth')
    parser.add_argument('--revision', required=True)
    args = parser.parse_args(argv)
    store = AccountProgress(args.data_root, account(args.client, args.uid))
    print(json.dumps(store.decision(theme=args.theme, capability=args.capability,
                                    revision=args.revision), ensure_ascii=False, indent=2))


if __name__ == '__main__': main()

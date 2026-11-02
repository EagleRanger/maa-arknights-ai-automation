"""Post-run comparison for the EXISTING daily executor; no live game imports."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ark_modules.core import ReceiptStore
from ark_modules.natural_review import review


def evaluate(report_path, manifest_path, output=None):
    report_path, manifest_path = Path(report_path), Path(manifest_path)
    before = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in (report_path,manifest_path)}
    report = json.loads(report_path.read_text(encoding='utf-8-sig'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    run = manifest.get('run_id','')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',run): raise ValueError('invalid run identity')
    if not manifest.get('finished_at'): raise ValueError('only settled natural runs may be reviewed')
    if (report.get('run_summary') or {}).get('run_evidence_boundary') != (manifest.get('run_summary') or {}).get('run_evidence_boundary'):
        raise ValueError('report/manifest boundary differs')
    if not (report.get('run_summary') or {}).get('run_evidence_boundary'):
        raise ValueError('missing run evidence boundary')
    target = Path(output) if output else ROOT/'outputs'/'module_reviews'/(run+'.json')
    if target.resolve() in (report_path.resolve(),manifest_path.resolve()): raise ValueError('cannot overwrite source')
    if target.exists():
        old=json.loads(target.read_text(encoding='utf-8'))
        if old.get('source_sha256')==before: return old
        raise ValueError('source changed; use a new review path and preserve prior result')
    if not report.get('execution_accounting'):
        from ark_modules.run_accounting import build
        report['execution_accounting']=build(report,manifest)
    result=review(report,manifest)
    result.update(source_sha256=before,source_report=str(report_path.resolve()),source_manifest=str(manifest_path.resolve()),
                  validation_kind='historical_or_natural_production_reference_not_candidate_acceptance')
    if any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest for p,digest in before.items()):
        raise ValueError('source changed during bounded review')
    ReceiptStore(target).save(result)
    return result


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--report',required=True);p.add_argument('--manifest',required=True);p.add_argument('--output')
    args=p.parse_args(argv)
    result=evaluate(args.report,args.manifest,args.output)
    print(json.dumps({'run_id':result['run_id'],'open_items':result['open_items'],'game_actions':0},ensure_ascii=False))


if __name__=='__main__':main()

"""Attach the shared module ledger at the existing final sink, once, read-only.

Does not reinterpret prior-day caches, alter battle policy, promote completion,
or run another popup. JSON, Markdown and the existing popup consume one ledger.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import json

from ark_modules.run_accounting import build, effect_lines


def balance_lines(report):
    rows = []
    validation = report.get('stamina_validation') or {}
    first, last = validation.get('start') or {}, validation.get('final') or {}
    if last.get('verified') is True and type(last.get('value')) is int:
        beginning = str(first['value']) if first.get('verified') is True and type(first.get('value')) is int else '起始未识别'
        rows.append(f"实时理智：{beginning} → {last['value']}/{last.get('max', 210)}。")
        if last.get('captured_at'):
            rows.append('余额实测于' + last['captured_at'] + '，之后恢复不计入本次读数。')
    else:
        rows.append('最终实时理智未确认，不引用旧余额。')
    if first.get('verified') is not True:
        rows.append('验收缺项：起始理智读数缺证；不抹掉已核实的战斗，也不因此重打。')
    return rows


def attach(report, manifest, *, log_paths=None):
    result = deepcopy(report)
    result['execution_accounting'] = build(result, manifest, log_paths=log_paths)
    return result


@contextmanager
def boundary(root):
    import daily_final_report_sink_v1 as presentation
    import daily_final_report_sink_v2 as sink
    import daily_plain_popup_v1 as plain
    old_reconcile, old_effects, old_popup = sink.reconcile_manifest, presentation.effect_lines, plain.summary

    def effects(report):
        ledger = report.get('execution_accounting') or {}
        if not ledger.get('facts'):
            return old_effects(report)
        lines = effect_lines(ledger) + balance_lines(report)
        if report.get('same_game_day_verified_totals'):
            # The sealed continuation aggregate remains separate from this run.
            lines += [line for line in old_effects(report) if line.startswith(('今日已验证累计', '其中此前', '今日累计掉落'))]
        return lines

    def popup(report):
        title, text, outcome = old_popup(report)
        ledger = report.get('execution_accounting') or {}
        if not ledger.get('facts'):
            return title, text, outcome
        replaced, lines = False, []
        for line in text.splitlines():
            if line.startswith(('本次理智用于', '今日理智用于', '理智作战：')):
                lines.extend(effects(report))
                replaced = True
            elif line.startswith(('理智余额：', '最后核实的理智：', '最后剩多少理智：')):
                continue
            else:
                lines.append(line)
        if not replaced:
            lines.extend(effects(report))
        farm = ((report.get('run_summary') or {}).get('event') or {}).get('farm') or {}
        if farm.get('status') == 'completed' and any(row['stage'] == farm.get('stage') for row in ledger.get('stages', [])):
            lines = [line.replace('本次没有核实到已通关关卡。', '本次材料刷取已核实；不计为新开荒关卡。') for line in lines]
        if (report.get('stamina_validation') or {}).get('start', {}).get('verified') is not True:
            lines = [line.replace('还有任务未完成，详情见同日完整报告',
                                  '起始理智未识别，整日验收未通过；已完成项已保留，详见完整报告') for line in lines]
            if outcome != 'verified':
                title = '明日方舟自动化：已有成果，仍有待核验项'
                lines[0] = title
        return title, '\n'.join(lines), outcome

    def reconcile(path, report, run_id):
        manifest = json.loads(Path(path).read_text(encoding='utf-8'))
        if manifest.get('run_id') != run_id:
            raise ValueError('accounting run identity mismatch')
        # Raise on mismatched run identity; missing log evidence is a recorded
        # partial ledger, not an excuse to replay the just-completed business.
        if (report.get('run_summary') or {}).get('run_evidence_boundary') != (manifest.get('run_summary') or {}).get('run_evidence_boundary'):
            raise ValueError('accounting report/manifest boundary mismatch')
        try:
            report.update(attach(report, manifest))
        except (OSError, ValueError, KeyError) as exc:
            # A presentation failure must not hide the original business
            # receipt or prevent the existing final popup and cleanup result.
            report['execution_accounting'] = dict(schema_version=1, run_id=run_id,
                coverage='partial', facts=[], issues=['accounting_unavailable: ' + str(exc)])
        result = old_reconcile(path, report, run_id)
        result['execution_accounting'] = deepcopy(report['execution_accounting'])
        presentation.write_json(Path(path), result)
        report_path = Path(root)/'outputs'/f"daily_report_{report['date']}.json"
        presentation.write_json(report_path, report)
        temporary = report_path.with_suffix('.md.accounting.tmp')
        temporary.write_text(presentation.markdown(report), encoding='utf-8')
        temporary.replace(report_path.with_suffix('.md'))
        return result

    with patch.object(sink, 'reconcile_manifest', reconcile), \
         patch.object(presentation, 'effect_lines', effects), patch.object(plain, 'summary', popup):
        yield

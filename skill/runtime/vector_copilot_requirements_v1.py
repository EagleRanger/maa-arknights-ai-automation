"""Recipient-opted-in attribute-independent trial; full operator selection stays.

Disabled unless the recipient explicitly sets ARK_COPILOT_STRICT_REQUIREMENTS=0.
Preserve the source job, names, chosen skills, groups, actions and notes.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from contextlib import contextmanager


def without_requirements(job):
    result = deepcopy(job)

    def visit(node):
        if isinstance(node, dict):
            if isinstance(node.get("requirements"), dict):
                node["requirements"] = {}
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    # Do not rewrite doc/examples or other metadata containing this word.
    visit(result.get("opers", []))
    visit(result.get("groups", []))
    return result


def trial_path(runtime, source, directory):
    source = Path(source)
    if os.environ.get('ARK_COPILOT_STRICT_REQUIREMENTS', '1').strip() != '0':
        return source
    original = json.loads(source.read_text(encoding="utf-8"))
    trial = without_requirements(original)
    if trial == original:
        return source
    path = Path(directory) / source.name
    path.parent.mkdir(parents=True, exist_ok=True)
    runtime._atomic_write_json(str(path), trial)
    if json.loads(path.read_text(encoding="utf-8")) != trial:
        raise RuntimeError("trial readback mismatch")
    runtime._atomic_write_json(str(path.with_suffix(".provenance.json")), {
        "source": str(source.resolve()),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest().upper(),
        "source_unchanged": True, "authority": "recipient_explicit_ARK_COPILOT_STRICT_REQUIREMENTS_0",
        "ignored": "elite, level, skill_level, module, potentiality recommendations",
        "preserved": "all operators/groups/skill choices/actions/doc; full formation and real outcome required",
    })
    return path


@contextmanager
def engine_boundary(runtime, directory):
    """Apply only the recipient's explicit opt-in in this daily process.

    Bind the existing relaxation hook, not a second battle starter. Missing
    units and actual formation/result checks remain in the original engine.
    """
    if os.environ.get('ARK_COPILOT_STRICT_REQUIREMENTS', '1').strip() != '0':
        yield
        return
    original = runtime._relaxed_copilot_job_path

    def relaxed(path):
        return str(trial_path(runtime, path, directory))

    runtime._relaxed_copilot_job_path = relaxed
    try:
        yield
    finally:
        runtime._relaxed_copilot_job_path = original

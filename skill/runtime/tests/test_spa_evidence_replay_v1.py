from tools.verify_spa_trial_evidence_v1 import audit_callbacks


def e(msg,**details):return dict(msg=msg,details=details)


def test_real_callback_names_and_post_completion_stop():
    result=audit_callbacks([e(20002,details={'task':'ReturnHome'}),
                            e(10002,taskchain='Custom'),e(10004,taskchain='Custom')])
    assert result['native_cycle_verified'] and not result['errors_before_completion']


def test_earlier_error_and_missing_home_cannot_pass():
    assert not audit_callbacks([e(10000,taskchain='Custom'),
        e(20002,details={'task':'ReturnHome'}),e(10002,taskchain='Custom')])['native_cycle_verified']
    assert not audit_callbacks([e(10002,taskchain='Custom')])['native_cycle_verified']

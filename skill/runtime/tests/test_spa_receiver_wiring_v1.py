"""Receiver startup seams only; no DLL, network, device or daily action."""
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from tools import run_spa_trial_v1 as host
import daily_portable_bootstrap_v1 as bootstrap
import maa_spa_resources_v1 as resources


@pytest.mark.parametrize('synchronize',[False,True])
def test_preflight_uses_recipient_tree_without_author_handoff(tmp_path,synchronize):
    installed=tmp_path/'MAA-App';out=tmp_path/'run';events=[]
    old_private=SimpleNamespace(read=Mock(side_effect=AssertionError('author handoff forbidden')))
    with patch.dict(sys.modules,{'daily_dispatch_v1':old_private}),\
         patch.object(bootstrap,'preflight',side_effect=lambda:events.append('receiver') or {'root':str(installed)}),\
         patch.object(resources,'synchronize',side_effect=lambda *a:events.append(('sync',a))),\
         patch.object(resources,'verify',side_effect=lambda *a:events.append(('verify',a))),\
         patch.object(resources,'native_probe',side_effect=lambda *a:events.append(('probe',a))):
        result=host.preflight(out,synchronize)
    assert events[0]=='receiver'
    assert events[1]==(('sync',(installed,out/'resources')) if synchronize else ('verify',(out/'resources',)))
    assert events[2]==('probe',(installed,out/'resources'))
    assert result['root']==str(installed) and result['daily_invoked'] is False
    old_private.read.assert_not_called()


def test_missing_receiver_setup_stops_before_download_or_core(tmp_path):
    with patch.object(bootstrap,'preflight',side_effect=RuntimeError('portable MAA missing')),\
         patch.object(resources,'synchronize') as sync,patch.object(resources,'native_probe') as probe:
        with pytest.raises(RuntimeError,match='portable MAA missing'):host.preflight(tmp_path,True)
    sync.assert_not_called();probe.assert_not_called()


def test_help_does_not_prepare_launch_or_start_daily(capsys):
    with patch.object(sys,'argv',['run_spa_trial_v1.py','--help']),\
         patch.object(host,'preflight') as preflight,patch.object(host,'launch') as launch:
        with pytest.raises(SystemExit) as ended:host.main()
    assert ended.value.code==0 and '--prepare' in capsys.readouterr().out
    preflight.assert_not_called();launch.assert_not_called()


def test_worker_import_closure_is_present_without_loading_real_environment():
    # Import-only validation catches omitted transitive files. These modules
    # must not perform real input, instantiate Core or read author registries.
    with patch.dict(sys.modules,{'uiautomation':SimpleNamespace(__file__='synthetic-uiautomation')}):
        for name in ('ark_host.process_lifetime_v1','ark_host.environment','ark_host.runtime_services_v3',
            'daily_runtime_target_v1','daily_game_update_v1','daily_login_supply_v4',
            'operator_home_labels_v1','ocr_tolerance_v1','daily_local_popup_v1',
            'event_daily_reward_chain_v2','operator_optional_inspection_v1',
            'daily_client_update_gate_v1','feature_acceptance_transport_v1','spa_core_trial_v1'):
            assert importlib.import_module(name) is not None

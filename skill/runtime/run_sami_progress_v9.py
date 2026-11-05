"""V8 with the proven supply/sign-in startup consumer and same-step AI repair."""
from unittest.mock import patch
import run_sami_progress_v8 as previous
import run_sami_progress_v1 as base
import arknights_daily_runtime_v12 as app
from daily_login_supply_v4 import boundary as supply
from event_daily_reward_chain_v1 import boundary as reward_chain

WORKFLOW='ARK-SAMI-PROGRESS-V9'


def main():
    import run_sami_until_deadline as sami
    old_run=sami.run
    old_admit=base.admit
    Base=previous.OwnerControl
    active={}
    def admit(*args, **kwargs):
        packet, deadline = old_admit(*args, **kwargs)
        choice = packet.get('exploration')
        if (not isinstance(choice, dict) or choice.get('difficulty') != 'highest_unlocked'
                or any(not isinstance(choice.get(name), str) or not choice[name].strip()
                       for name in ('core_char', 'squad', 'roles'))):
            raise ValueError('select your own Sami exploration settings; this route uses highest_unlocked')
        active['choice'] = choice
        return packet, deadline
    class StartupControl(Base):
        def __init__(self,**kwargs):
            super().__init__(**kwargs)
            active['control']=self
    def hold(reason,verify):
        result=active['control'].wait_for_repair('startup',dict(reason=reason),verify)
        return result.get('state','main_menu')
    def run(deadline, _preset_core, _preset_squad, _preset_roles, *args, **kwargs):
        # Installed after V1 shared services and account binding, at the real
        # startup caller. No daily full chain or daily cooperation host enters.
        with patch.object(app,'_startup_ai_wait',hold,create=True),supply(app),reward_chain():
            choice=active['choice']
            return old_run(deadline, choice['core_char'], choice['squad'], choice['roles'], *args, **kwargs)
    with patch.object(previous,'WORKFLOW',WORKFLOW),patch.object(previous,'OwnerControl',StartupControl), \
         patch.object(base,'admit',admit), \
         patch.object(sami,'run',run):
        return previous.main()


if __name__=='__main__':raise SystemExit(main())

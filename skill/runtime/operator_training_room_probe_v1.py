"""Only the existing MAA Training facility: observe/claim, never replace staff."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from operator_training_v1 import parent_receipts
from operator_training_infrast_v1 import observation,service,KEY

def run(app,output):
    from ark_modules.core import ReceiptStore
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    if (out/'receipt.json').exists():raise ValueError('existing room probe preserved')
    if app._maa_task_queue_running() is not False:raise ValueError('MAA queue owns device')
    path=Path(app.MAA_CONFIG)/'gui.new.json';original=app._read_json_file(str(path),{})
    desired=deepcopy(original)
    task=next(row for row in app._task_queue(desired) if row.get('TaskType')=='Infrast')
    plan=out/'training-only.json'
    ReceiptStore(plan).save(dict(plans=[dict(name='保留当前训练位与协助者',rooms={'training':[{'skip':True}]})]))
    task.update(Mode='Custom',RoomList=[{'Room':'Training'}],Filename=str(plan),PlanSelect=0,
        ContinueTraining=False,UsesOfDrones='_NotUse',OriginiumShardAutoReplenishment=False,
        FiammettaRecoveryEnabled=False)
    app._set_enabled_tasks(desired,{'Infrast'})
    ReceiptStore(out/'configuration.before.json').save(original)
    row=dict(status='unverified',whole_base_invoked=False,daily_invoked=False,combat_invoked=False,
             room='Training',new_training_requested=False,staff_replacement_requested=False)
    try:
        app._atomic_write_json(str(path),desired)
        if app._maa_process_exists():app.reload_maa_after_config_switch('只核训练室，不轮换其他基建')
        with parent_receipts(app):
            if not app.run_maa_daily_tasks(enabled_tasks={'Infrast'}):raise RuntimeError('Training facility queue start unverified')
            returned=app.wait_maa_complete(timeout=300,continue_after_chain_error=True,prestarted_boundary=True)
            text=app._get_current_maa_run_log();proof=out/'queue.log';proof.write_text(text,encoding='utf-8')
            room=observation(text)
            row.update(status='native_room_observed' if returned and room.get('infrast_chain_verified') else 'unverified',
                       observation=room,evidence=str(proof))
            if returned and room.get('status')=='processing':
                # Actual current room -> actual new bridge, not a fabricated
                # OperProgress success or a second navigation/test queue.
                app._RUN_SUMMARY[KEY]=room
                row['goal_router']=service(app)
            if app._maa_task_queue_running() is False:
                frame=Path(app.shot('native_training_room_result'));shutil.copy2(frame,out/'game_after_queue.png')
                row['screenshot']=str(out/'game_after_queue.png')
    finally:
        if app._maa_task_queue_running() is False:
            if app._maa_process_exists():app.reload_maa_after_config_switch('还原训练室单项核验配置')
            app._atomic_write_json(str(path),original)
            row['configuration_restored']=app._read_json_file(str(path),{})==original
        else:row['configuration_restored']=False
        ReceiptStore(out/'receipt.json').save(row)
    return row

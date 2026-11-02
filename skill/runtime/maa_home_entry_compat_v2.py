"""Observed 2.7.91 home entry-label variants, additive and ROI preserving."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import json
import shutil
import hashlib
import maa_home_template_compat_v1 as v1
from portable_resources_v1 import local_visual_path

ROOT=Path(__file__).resolve().parent
# Recipient-only crops from their own MAA-base home. No author pixels bundled.
ENTRIES={
 'Infrast':('InfrastDefault','CodexHomeInfrast2791.png',(941,554,1033,616)),
 'Recruit':('RecruitDefault','CodexHomeRecruit2791.png',(978,474,1115,524)),
 'Mall':('MallDefault','CodexHomeMall2791.png',(778,458,893,511)),
 'Task':('TaskDefault','CodexHomeTask2791.png',(737,538,825,606)),
 'Depot':('DepotDefault','CodexHomeDepot2791.png',(1151,592,1221,632)),
 'Friends':('FriendsDefault','CodexHomeFriends2791.png',(356,539,413,573)),
 'Terminal':('TerminalDefault','CodexHomeTerminal2791.png',(915,143,1034,213)),
}

def ensure(root):
    root=Path(root);records=[]
    for file,(task,name,box) in ENTRIES.items():
        fixture=local_visual_path('maa_home_entry_'+file.lower())
        if fixture is None:
            records.append(dict(task=task,status='recipient_reference_required',changed=False))
            continue
        path=root/'resource/tasks/UiTheme'/(file+'.json')
        if not path.is_file():continue
        raw=path.read_bytes();tasks=json.loads(raw.decode('utf-8-sig'))
        original=tasks[task]['template']
        templates=[original] if isinstance(original,str) else original
        target=root/'resource/template/UiTheme/CodexHome2791'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and v1.sha(target)!=v1.sha(fixture):raise ValueError('entry fixture conflict')
        if not target.exists():shutil.copy2(fixture,target)
        if name not in templates:
            backup=ROOT/'outputs/maa_resource_backups'/(file+'.entry-v2.'+hashlib.sha256(raw).hexdigest()[:16]+'.json')
            backup.parent.mkdir(parents=True,exist_ok=True)
            if not backup.exists():shutil.copy2(path,backup)
            tasks[task]['template']=[*templates,name]
            path.write_text(json.dumps(tasks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            if json.loads(path.read_text('utf-8'))!=tasks:raise ValueError('entry readback mismatch')
        records.append(dict(task=task,template=name,sha256=v1.sha(target)))
    # MAA's real SwitchTheme task has an implicit template, not an explicit one.
    glyph=local_visual_path('maa_home_2791')
    installed=root/'resource/template/UiTheme/SwitchTheme'/v1.NEW
    if glyph is None or not installed.is_file() or v1.sha(glyph)!=v1.sha(installed):
        return records  # Never register a missing/unverified compatibility template.
    path=root/'resource/tasks/UiTheme/SwitchTheme.json'
    raw=path.read_bytes();tasks=json.loads(raw.decode('utf-8-sig'))
    task=tasks['SwitchTheme@ToggleSettingsMenu']
    if 'template' not in task:
        backup=ROOT/'outputs/maa_resource_backups'/('SwitchTheme.implicit-v2.'+hashlib.sha256(raw).hexdigest()[:16]+'.json')
        if not backup.exists():shutil.copy2(path,backup)
        task['template']=[v1.OLD,v1.NEW]
        path.write_text(json.dumps(tasks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return records

@contextmanager
def boundary():
    import daily_portable_bootstrap_v1 as bootstrap
    original=bootstrap.resource_paths
    @contextmanager
    def paths(*args,**kwargs):
        with original(*args,**kwargs) as info:
            print('ARK_HOME_ENTRIES '+json.dumps(ensure(info['root']),ensure_ascii=False),flush=True)
            yield info
    with patch.object(bootstrap,'resource_paths',paths):yield

if __name__=='__main__':
    import argparse
    from tools.collect_portable_resources_v1 import collect
    parser=argparse.ArgumentParser(description='Collect tiny labels from your own MAA 1280x720 home capture')
    parser.add_argument('--source',required=True,type=Path)
    args=parser.parse_args()
    for file in ENTRIES:
        print(json.dumps(collect('maa_home_entry_'+file.lower(),args.source),ensure_ascii=False))

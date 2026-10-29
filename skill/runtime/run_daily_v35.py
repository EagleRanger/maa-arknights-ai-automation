"""Daily V35: DP card-carousel navigation and safe exit."""
from __future__ import annotations
from portable_paths import resolve_path as _portable_path
import hashlib,json,sys
from datetime import datetime
from pathlib import Path
import run_daily_v19 as v19
import run_daily_v22 as v22
import run_daily_v23 as v23
import run_daily_v24 as v24
import run_daily_v25 as v25
import run_daily_v26 as v26
import run_daily_v27 as v27
ROOT=Path(__file__).resolve().parent; ENTRYPOINT="run_daily_v35.py --mode full"
def check_entry(at=None):
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window
    import dp_event_route_v26 as dp
    h=json.loads((ROOT/".project-reasoning"/"AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")); c=json.loads((ROOT/"PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if h.get("status")!="active" or h.get("entrypoint")!=ENTRYPOINT: raise ValueError("Stable daily V35 entry is not active")
    if h["workflow_binding"]["contract_goal_revision"]!=c["goal_memory"]["revision"]: raise ValueError("Contract and V35 disagree")
    gate=resolve_production_recipes(ROOT/".project-reasoning"/"COMPONENTS.json",h["required_recipes"]); reg=json.loads((ROOT/".project-reasoning"/"COMPONENTS.json").read_text(encoding="utf-8")); ids={x for r in gate["resolved"] for x in r["components"]}
    for comp in reg["components"]:
        if comp["id"] not in ids: continue
        for a in comp.get("artifacts",[]):
            p=(ROOT/a["path"]).resolve(); p.relative_to(ROOT)
            if hashlib.sha256(p.read_bytes()).hexdigest().upper()!=a["sha256"].upper(): raise ValueError("Production artifact changed: "+a["path"])
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper()!=h["production_snapshot_sha256"].upper(): raise ValueError("V35 entry snapshot changed")
    now=at or datetime.now().astimezone(); return {"status":"PASS","entrypoint":h["entrypoint"],"recipe":h["required_recipes"],"checked_at":now.isoformat(),"sss_window":reward_window(now),"runtime":v19._runtime_probe(),"dp_resource_probe":dp.probe_dp_resources(Path(_portable_path('maa'))),"dp_cards":"strict_clipped_DP1_and_bounded_exit","game_actions":0}
def install_v35_runtime_adapters():
    v27.install_v27_runtime_adapters(); import run_daily_v18 as v18
    current=v18.install_v18_runtime_adapters
    if getattr(current,"_daily_v35_bound",False): return
    def install_all():
        runtime=current(); import dp_event_cards_v35 as cards; cards.install(runtime); return runtime
    install_all._daily_v35_bound=True; v18.install_v18_runtime_adapters=install_all
def main():
    v19._ensure_verified_runtime(); import run_daily as base; import run_daily_v18 as v18
    install_v35_runtime_adapters(); base.ENGINE_SHA256=hashlib.sha256((ROOT/"arknights_daily_runtime_v12.py").read_bytes()).hexdigest().upper()
    for m in (base,v18,v19,v22,v23,v24,v25,v26,v27): m.check_entry=check_entry
    return v19.main()
def cli(argv=None):
    args=list(sys.argv[1:] if argv is None else argv); v19._ensure_verified_runtime(args)
    if args==["--check-only"]: print(json.dumps(check_entry(),ensure_ascii=False)); return 0
    return main()
if __name__=="__main__": raise SystemExit(cli())

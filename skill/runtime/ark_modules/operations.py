"""Single explicit operation catalogue; no last-installed-patch dispatch."""
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True)
class Operation:
    name: str
    domain: str
    function: str
    required: tuple[str, ...] = ()
    legacy_modes: tuple[str, ...] = ()
    read_only: bool = False

    def bind(self):
        return getattr(import_module('ark_modules.domains.' + self.domain), self.function)


CATALOGUE = (
    Operation('weekly.annihilation', 'weekly', 'weekly',
              ('_run_full_annihilation_step', '_read_terminal_annihilation_weekly_progress')),
    Operation('activity.stage', 'activity', 'stage',
              ('_event_execution_stages', '_event_stage_modes', 'clear_event_stage',
               'verify_event_challenge_cleared', 'verify_event_stage_cleared')),
    Operation('activity.rewards', 'activity', 'rewards', ('claim_event_task_rewards',)),
    Operation('activity.farm', 'farming', 'farm',
              ('_configure_new_event_farm_from_live_inventory', 'mode_event', '_capture_stamina_observation'), ('mode_event',)),
    Operation('resource.farm', 'farming', 'resource',
              ('mode_resource', '_capture_stamina_observation'), ('mode_resource',)),
    Operation('mainline.stage', 'mainline', 'mainline', ('mode_mainline',), ('mode_mainline',)),
    Operation('periodic.sss', 'periodic', 'sss', ('mode_security',), ('mode_security',)),
    Operation('base.prepare', 'base', 'prepare_base', ('prepare_dynamic_333_base',)),
    Operation('base.rooms', 'base', 'rooms'),
    Operation('base.drones', 'base', 'drones'),
    Operation('daily.final', 'daily', 'daily',
              ('goto_main_menu', '_initialize_current_run_evidence_boundary', 'run_maa_daily_tasks',
               'wait_maa_complete', '_get_current_maa_run_log', '_taskchain_status')),
    Operation('daily.exit_tail', 'daily', 'exit_tail',
              ('goto_main_menu', 'ocr_text', 'ocr', 'tap', 'wait', '_task_queue', '_read_json_file', '_atomic_write_json',
               '_initialize_current_run_evidence_boundary', 'run_maa_daily_tasks',
               'wait_maa_complete', '_get_current_maa_run_log', '_taskchain_status',
               '_maa_process_exists', 'reload_maa_after_config_switch')),
    Operation('long.roguelike', 'exploration', 'long'),
    Operation('long.reclamation', 'exploration', 'long'),
    Operation('observe', 'observation', 'observe', ('ocr',), read_only=True),
)
BY_NAME = {row.name: row for row in CATALOGUE}


def select(operations=None):
    names = set(BY_NAME if operations is None else operations) - {'preserve', 'hold'}
    unknown = names - BY_NAME.keys()
    if unknown:
        raise ValueError('unknown business operations: ' + ','.join(sorted(unknown)))
    return tuple(row for row in CATALOGUE if row.name in names)


def describe(operations=None):
    """Offline dependency inventory, without importing or preparing a runtime."""
    return [{'operation': row.name, 'domain': row.domain,
             'entry': f'ark_modules.domains.{row.domain}:{row.function}',
             'required_interfaces': list(row.required), 'read_only': row.read_only}
            for row in select(operations)]

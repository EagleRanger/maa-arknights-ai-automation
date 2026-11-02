"""Local OCR repair continuation; retain the saved-400 evidence source."""
from unittest.mock import patch
import run_daily_weekly_postclear_v1 as previous
import daily_weekly_postclear_v1 as scope
from annihilation_postclear_v2 import service
from run_daily_v103 import ROOT, read, sha, check_entry as BASE_CHECK

WORKFLOW='ARK-WEEKLY-POSTCLEAR-V2'
run_scope=scope.run_scope


def check_entry(at=None,packet=None):
    if not packet or packet.get('workflow')!=WORKFLOW or packet.get('scope')!='saved_400_rewards_weekly_remaining_stamina_post_daily':
        raise ValueError('postclear V2 binding missing')
    if packet.get('resources')!='existing_sanity_only_no_refills':raise ValueError('resources differ')
    result=BASE_CHECK(at,packet)
    source=read(ROOT/packet['source_manifest'])
    if sha(ROOT/packet['source_manifest'])!=packet['source_sha256']:raise ValueError('source changed')
    clear=packet['saved_clear'];proof=packet['saved_clear_source']
    sealed=read(ROOT/proof['manifest'])
    if (sha(ROOT/proof['manifest'])!=proof['sha256'] or clear['source_run_id']!=sealed['run_id']
            or clear['stage_id']!=packet['stage_id'] or clear['kills']!=400 or clear['leaked']!=0
            or clear['defense']<=0 or clear['saved'] is not True):
        raise ValueError('real saved 400 lineage changed')
    return result


def main(argv=None):
    with patch.object(previous,'check_entry',check_entry),patch.object(previous,'full',full):
        return previous.main(argv)


def full(packet,source,bundle):
    host=previous.host
    with patch.object(scope,'service',service),patch.object(host,'WORKFLOW',WORKFLOW), \
         patch.object(host,'__file__',__file__),patch.object(host,'check_entry',check_entry), \
         patch.object(host,'run_scope',run_scope):return host.full(packet,source,bundle)


if __name__=='__main__':raise SystemExit(main())

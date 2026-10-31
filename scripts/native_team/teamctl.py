#!/usr/bin/env python3
"""Four ChatGPT scheduled-worker lanes: local control plane for isolated source work.

No model execution, API, GPU, deploy or network. Review gate is mandatory.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import coordinator as c
import golden_evidence as ge

LANES={'R':'renderer','Q':'qa','G':'golden','S':'reliability'}
ROOT=Path(__file__).resolve().parent.parent
DB=ROOT/'state/team.sqlite3'
SEED=[
 ('R-01','Source-grounded bimanual contact', 'Review PR47 pre-GPU actor-relative prop+hands architecture on NEW heldout case. No map rerolls or GPUs. One negative regression first.', ['worker/bimanual_scene_planner.py','tests/bimanual-scene-planner.test.py']),
 ('R-02','Generalized staged prop and ROI', 'Audit generic compositor vs source plate and actor masks, failing contact/garment negative test. No posthoc fixed-coordinate hacks.', ['worker/prop_layer_compositor.py','tests/prop-layer-compositor.test.py']),
 ('Q-01','Strict source-provenance gate', 'Review previous pilot worker-a uncommitted diff on PC as read-only source, then reproduce/apply to this independent PR49 branch with tests. No mixing scene/frame/actor evidence.', ['worker/atomic_prop_gate.py','tests/atomic-prop-gate.test.py']),
 ('Q-02','Semantic QA observability contract', 'Trace missing required scene evidence without loosening PASS; build narrow negative tests for unknown contact.', ['worker/qa_evidence_fence.py','tests/qa-evidence-fence.test.py']),
 ('G-01','Golden manifest independent review', 'Review previous pilot worker-b commit 5a3ccd9. Find one real false accept in 30+ labeled synthetic manifest validator and fix with negative test; only synthetic data.', ['scripts/render_golden_set_audit.py','scripts/tests/test_render_golden_set_audit.py']),
 ('G-02','Honest visual QA metrics', 'Implement offline confusion-matrix metrics for human labels incl unknown/unobservable, protect against empty labels; no private PNG publication.', ['scripts/render_quality_metrics.py','scripts/tests/test_render_quality_metrics.py']),
 ('S-01','Atomic publish version fence', 'Reproduce stale candidate version/scene collision in source code, implement isolated source-only policy and negative test. No production deploy.', ['scripts/render_publish_fence.py','scripts/tests/test_render_publish_fence.py']),
 ('S-02','Crash/restart/rollback tests', 'Isolated offline E2E crash/retry/save preservation contract, no GPU or production service manipulation.', ['scripts/render_e2e_rehearsal.py','scripts/tests/test_render_e2e_rehearsal.py']),
]

def git(lane,*args):
    p=subprocess.run(['git','-C',str(ROOT/('lane-'+LANES[lane])),*args],capture_output=True,text=True,timeout=15)
    if p.returncode:raise RuntimeError('git error: '+p.stderr[:200])
    return p.stdout.strip()

def paths_valid(xs):
    return isinstance(xs,list) and bool(xs) and len(xs)<12 and all(isinstance(x,str) and x and not x.startswith(('/','.git')) and '\\' not in x and all(y not in ('','.','..') for y in x.split('/')) for x in xs)

def _checked_scope(lane, paths):
    """Reject paths escaping an isolated Git worktree through symlinks."""
    if not paths_valid(paths):
        raise ValueError('invalid task scope')
    root = (ROOT / ('lane-' + LANES[lane])).resolve()
    for path in paths:
        actual = (root / path).resolve()
        if not actual.is_relative_to(root):
            raise ValueError('scope escapes lane worktree')
    return paths


def _safe_source_diff(lane, baseline, head, allowed):
    """Prove exact lineage and changed paths, independent of moving lane HEAD."""
    if not baseline or not head or len(baseline) != 40 or len(head) != 40:
        raise ValueError('invalid Git SHA')
    if subprocess.run(
        ['git', '-C', str(ROOT / ('lane-' + LANES[lane])),
         'merge-base', '--is-ancestor', baseline, head],
        capture_output=True, timeout=15
    ).returncode != 0:
        raise ValueError('submitted commit not descended from claim baseline')
    changed = git(lane, 'diff', '--name-only', baseline, head).splitlines()
    if not changed or not set(changed).issubset(set(allowed)):
        raise ValueError('submitted commit has empty or out-of-scope diff')
    _checked_scope(lane, changed)
    # No symlinks or gitlinks in files provided by an untrusted worker.
    for file in changed:
        entry = git(lane, 'ls-tree', head, '--', file)
        for line in entry.splitlines():
            mode = line.split()[0] if line.split() else ''
            if mode in ('120000', '160000'):
                raise ValueError('symlink or submodule in worker output')
    errors = subprocess.run(
        ['git', '-C', str(ROOT / ('lane-' + LANES[lane])),
         'diff', '--check', baseline, head],
        capture_output=True, text=True, timeout=15
    )
    if errors.returncode:
        raise ValueError('Git diff whitespace checks failed')
    return changed


def open_db():
    if not DB.is_file():raise FileNotFoundError('not initialized')
    db=c.database(DB)
    db.execute('CREATE TABLE IF NOT EXISTS team_meta(k TEXT PRIMARY KEY,v TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS claim_baselines(task_id TEXT PRIMARY KEY, head TEXT NOT NULL)')
    ge.ensure_schema(db)
    return db

def initialize():
    if DB.exists():raise FileExistsError('Already initialized')
    DB.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    for lane in LANES:
        work=ROOT/('lane-'+LANES[lane])
        if not (work/'AGENTS.md').is_file() or not (work/'docs/DEVELOPMENT-AND-TESTING.md').is_file():
            raise RuntimeError('mandatory docs missing')
        if git(lane,'status','--porcelain'):
            raise RuntimeError('dirty lane')
    db=open_db() if DB.is_file() else c.database(DB)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS team_meta(k TEXT PRIMARY KEY,v TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS claim_baselines(task_id TEXT PRIMARY KEY, head TEXT NOT NULL)')
        db.execute("INSERT INTO team_meta VALUES ('state','active')")
        db.execute("INSERT INTO team_meta VALUES ('goal','render-v1 issue #20 Sprite + 3 CG first-shot, 30+ human-labeled independent G2/G3')")
        for tid,name,instructions,scope in SEED:
            c.add(db,tid,'source_inventory',scope,goal='render-v1 #20 '+name,priority=100 if tid.endswith('01') else 50)
            db.execute('UPDATE task SET action=? WHERE id=?',(instructions,tid))
        c.emit(db,'TEAM','initialized','4 isolated lanes; no GPU')
    finally:db.close()
    return {'ready':True,'root':str(ROOT),'tasks':len(SEED)}

def claim(db,lane,owner):
    assert_current_boot(db)
    if db.execute("SELECT v FROM team_meta WHERE k='state'").fetchone()[0]!='active':return {'claimed':False,'reason':'paused'}
    if git(lane,'status','--porcelain','--untracked-files=all'):
        return {'claimed':False,'reason':'dirty_worktree_needs_review'}
    # Check every queued scope before a worker gets write access.
    for pending in db.execute("SELECT paths,action FROM task WHERE id LIKE ? AND state='pending'", (lane+'-%',)):
        scope=json.loads(pending['paths'])
        if pending['action']=='visual_evidence':
            if lane!='G' or scope!=[]:
                raise ValueError('invalid visual-evidence task scope')
        else:
            _checked_scope(lane, scope)
    # Co.claim is serialized by BEGIN IMMEDIATE, with a narrow lane prefix.
    item=c.claim(db,owner,ttl=2700,lane=lane)
    if item is None:return {'claimed':False,'reason':'no_unclaimed_ready_task'}
    if item['action']!='visual_evidence':
        db.execute('INSERT OR REPLACE INTO claim_baselines(task_id,head) VALUES(?,?)',(item['id'],git(lane,'rev-parse','HEAD')))
    task=db.execute('SELECT paths,action FROM task WHERE id=?',(item['id'],)).fetchone()
    return {'claimed':True,**item,'lane':lane,'worktree':str(ROOT/('lane-'+LANES[lane])),
            'paths':json.loads(task['paths'])}

def submit(db,lane,owner,fence,tid,file):
    assert_current_boot(db)
    if not tid.startswith(lane+'-'):
        raise ValueError('wrong worker lane for task')
    original = Path(file)
    if original.is_symlink():
        raise ValueError('symlink evidence is forbidden')
    f = original.resolve()
    base = (ROOT/'evidence'/LANES[lane]).resolve()
    if not f.is_file() or base not in f.parents or f.stat().st_size>16000:
        raise ValueError('evidence must be a small private file in lane evidence dir')
    raw = f.read_bytes()
    result = json.loads(raw)
    if result.get('source_status')!='tested_isolated' or result.get('g2')!='UNVERIFIED' or result.get('g3')!='NO_GO':
        raise ValueError('source-only result cannot assert visual quality')
    tests=result.get('tests')
    if not isinstance(tests,list) or not tests or not all(isinstance(t,str) and t.strip() for t in tests):
        raise ValueError('nonempty test descriptions required')
    changed=result.get('changed_paths')
    if not paths_valid(changed):
        raise ValueError('invalid changed paths')
    row=db.execute('SELECT paths,state,owner,fence FROM task WHERE id=?',(tid,)).fetchone()
    if row is None or row['state']!='leased' or row['owner']!=owner or row['fence']!=fence:
        raise ValueError('submit without current fenced lease')
    allowed=_checked_scope(lane,json.loads(row['paths']))
    baseline=db.execute('SELECT head FROM claim_baselines WHERE task_id=?',(tid,)).fetchone()
    if not baseline:
        raise ValueError('missing source SHA')
    if git(lane,'status','--porcelain','--untracked-files=all'):
        raise ValueError('uncommitted files cannot be submitted')
    head=git(lane,'rev-parse','HEAD')
    committed=_safe_source_diff(lane,baseline[0],head,allowed)
    if set(committed)!=set(changed) or len(committed)!=len(changed):
        raise ValueError('evidence changed paths differ from exact commit')
    record={'sha256':hashlib.sha256(raw).hexdigest(),
            'path':str(f.relative_to(ROOT)),
            'tests':tests,
            'status':'source-only',
            'lane':lane,
            'baseline_sha':baseline[0],
            'commit_sha':head,
            'changed_paths':committed}
    return {'accepted':c.complete(db,tid,owner,fence,record,passed=True),
            'commit_sha':head}


def review(db,task_id,approve,note,verified_commit_sha=None):
    if not isinstance(note,str) or len(note.strip())<12:
        raise ValueError('independent review note required')
    x=db.execute('SELECT state,result,paths,action FROM task WHERE id=?',(task_id,)).fetchone()
    if x and x['action']=='visual_evidence':
        raise ValueError('visual receipt requires independent review-visual')
    if not x or x['state']!='review_pending':
        return {'approved':False,'reason':'not pending'}
    doc=json.loads(x['result'])
    lane=doc.get('lane')
    if lane not in LANES or not task_id.startswith(lane+'-'):
        raise ValueError('task evidence lane mismatch')
    original=ROOT/doc['path']
    f=original.resolve()
    if original.is_symlink() or (ROOT/'evidence'/LANES[lane]).resolve() not in f.parents:
        raise ValueError('evidence path outside private lane')
    if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=doc['sha256']:
        raise ValueError('evidence tampered')
    declared=json.loads(f.read_text())
    if declared.get('g2')!='UNVERIFIED' or declared.get('g3')!='NO_GO':
        raise ValueError('visual release claim unsupported')
    if approve and verified_commit_sha!=doc.get('commit_sha'):
        raise ValueError('reviewer must explicitly acknowledge exact submitted commit SHA')
    paths=_safe_source_diff(
        lane,doc.get('baseline_sha'),doc.get('commit_sha'),
        _checked_scope(lane,json.loads(x['paths'])))
    if sorted(paths)!=sorted(doc.get('changed_paths',[])) or sorted(paths)!=sorted(declared.get('changed_paths',[])):
        raise ValueError('submitted Git commit does not match evidence')
    # CAS review decision and audit event in ONE SQLite transaction.
    db.execute('BEGIN IMMEDIATE')
    try:
        current=db.execute('SELECT state,result FROM task WHERE id=?',(task_id,)).fetchone()
        if current is None or current['state']!='review_pending' or current['result']!=x['result']:
            db.execute('ROLLBACK')
            return {'approved':False,'reason':'review state changed'}
        updated=db.execute("UPDATE task SET state=? WHERE id=? AND state='review_pending'",
                           ('done' if approve else 'blocked',task_id))
        if updated.rowcount != 1:
            raise RuntimeError('lost review state CAS')
        c.emit(db,task_id,'review_pass' if approve else 'review_block',
               (note+'; verified_commit='+doc['commit_sha'][:12])[:400])
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction: db.execute('ROLLBACK')
        raise
    return {'approved':approve,'task':task_id,'verified_commit':doc['commit_sha']}



def boot_id():
    """Linux boot identity, safe to log; changing across reboots."""
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def assert_current_boot(db):
    """Prevent stale post-reboot worker heartbeats/submissions before watchdog."""
    previous=db.execute("SELECT v FROM team_meta WHERE k='boot_id'").fetchone()
    if previous and previous['v']!=boot_id():
        raise RuntimeError('host reboot detected; watchdog must reconcile interrupted leases')


def watchdog(db,observed_boot_id=None):
    now=time.time()
    db.execute('BEGIN IMMEDIATE')
    try:
        current_boot=observed_boot_id or boot_id()
        previous=db.execute("SELECT v FROM team_meta WHERE k='boot_id'").fetchone()
        rebooted=previous is not None and previous['v']!=current_boot
        if previous is None:
            db.execute("INSERT INTO team_meta(k,v) VALUES('boot_id',?)",(current_boot,))
            c.emit(db,'TEAM','boot_baseline','initial boot identity established')
        elif rebooted:
            interrupted=db.execute("SELECT id FROM task WHERE state='leased'").fetchall()
            for row in interrupted:
                db.execute("UPDATE task SET state='blocked',owner=NULL,fence=NULL,lease_until=0 "
                           "WHERE id=? AND state='leased'",(row['id'],))
                c.emit(db,row['id'],'reboot_interrupted','lease fenced and blocked after host restart')
            db.execute("UPDATE team_meta SET v=? WHERE k='boot_id'",(current_boot,))
            c.emit(db,'TEAM','boot_changed',str(len(interrupted))+' interrupted leases; no blind retry')
        # In forked coordinator: lease expiry blocks, no blind retry.
        c._expire(db,now)
        warnings=[]
        for prefix,name in LANES.items():
            vals=[dict(x) for x in db.execute('SELECT id,state,attempt,owner FROM task WHERE id LIKE ?', (prefix+'-%',))]
            if any(v['state']=='blocked' for v in vals):warnings.append(f'{name}:BLOCKED')
            if not any(v['state']=='leased' for v in vals):
                warnings.append(f'{name}:idle_or_waiting_for_next_scheduled_chat')
        current='; '.join(warnings)
        previous=db.execute("SELECT v FROM team_meta WHERE k='watchdog_warnings'").fetchone()
        if previous is None or previous['v'] != current:
            db.execute("INSERT OR REPLACE INTO team_meta(k,v) VALUES('watchdog_warnings',?)",(current,))
            c.emit(db,'TEAM','watchdog_state',current)
        # No repetitive event per minute: timestamp is in watchdog-latest.json.
        db.execute('COMMIT')
    except BaseException:db.execute('ROLLBACK');raise
    return {'watchdog_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'warnings':warnings}

def status(db):
    result={'team':db.execute("SELECT v FROM team_meta WHERE k='state'").fetchone()[0],'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'lanes':{},'g2':'UNVERIFIED','g3':'NO_GO'}
    for lane,name in LANES.items():
        tasks=[{'id':x['id'],'state':x['state'],'attempt':x['attempt'],'owner':x['owner'],'lease_until':x['lease_until']} for x in db.execute('SELECT * FROM task WHERE id LIKE ? ORDER BY id',(lane+'-%',))]
        result['lanes'][name]={'tasks':tasks,'head':git(lane,'rev-parse','--short','HEAD'), 'dirty':bool(git(lane,'status','--porcelain','--untracked-files=all'))}
    result['last_events']=[dict(x) for x in db.execute('SELECT ts,task_id,kind,detail FROM event ORDER BY seq DESC LIMIT 12')]
    return result

def main():
    p=argparse.ArgumentParser()
    subs=p.add_subparsers(dest='cmd',required=True)
    subs.add_parser('init');subs.add_parser('status');subs.add_parser('watchdog')
    cc=subs.add_parser('claim');cc.add_argument('--lane',choices=LANES,required=True);cc.add_argument('--owner',required=True)
    cc=subs.add_parser('heartbeat');cc.add_argument('--task',required=True);cc.add_argument('--owner',required=True);cc.add_argument('--fence',required=True)
    cc=subs.add_parser('submit');cc.add_argument('--lane',choices=LANES,required=True);cc.add_argument('--task',required=True);cc.add_argument('--owner',required=True);cc.add_argument('--fence',required=True);cc.add_argument('--evidence',required=True)
    cc=subs.add_parser('review');cc.add_argument('--task',required=True);cc.add_argument('--approve',action='store_true');cc.add_argument('--note',required=True);cc.add_argument('--verified-commit')
    cc=subs.add_parser('enqueue-visual');cc.add_argument('--spec',required=True)
    cc=subs.add_parser('submit-visual');cc.add_argument('--task',required=True);cc.add_argument('--owner',required=True);cc.add_argument('--fence',required=True);cc.add_argument('--evidence',required=True)
    cc=subs.add_parser('review-visual');cc.add_argument('--task',required=True);cc.add_argument('--reviewer',required=True);cc.add_argument('--approve',action='store_true');cc.add_argument('--note',required=True);cc.add_argument('--verified-png-sha')
    cc=subs.add_parser('enqueue');cc.add_argument('--spec',required=True)
    cc=subs.add_parser('stop');cc.add_argument('--reason',required=True)
    args=p.parse_args()
    if args.cmd=='init':print(json.dumps(initialize()));return 0
    db=open_db()
    try:
        if args.cmd=='status':result=status(db)
        elif args.cmd=='watchdog':result=watchdog(db)
        elif args.cmd=='claim':result=claim(db,args.lane,args.owner)
        elif args.cmd=='heartbeat':
            assert_current_boot(db)
            result={'accepted':c.heartbeat(db,args.task,args.owner,args.fence,ttl=2700)}
        elif args.cmd=='submit':result=submit(db,args.lane,args.owner,args.fence,args.task,args.evidence)
        elif args.cmd=='review':result=review(db,args.task,args.approve,args.note,args.verified_commit)
        elif args.cmd=='enqueue-visual':
            assert_current_boot(db)
            result=ge.enqueue(db,json.loads(Path(args.spec).read_text()))
        elif args.cmd=='submit-visual':
            assert_current_boot(db)
            result=ge.submit(db,args.task,args.owner,args.fence,args.evidence)
        elif args.cmd=='review-visual':
            assert_current_boot(db)
            result=ge.review(db,args.task,args.reviewer,args.approve,args.note,args.verified_png_sha)
        elif args.cmd=='enqueue':
            d=json.loads(Path(args.spec).read_text())
            if d['lane'] not in LANES or not d['id'].startswith(d['lane']+'-'):
                raise ValueError('invalid lane/task ID')
            _checked_scope(d['lane'],d['paths'])
            deps=d.get('dependencies',[])
            if not isinstance(deps,list) or len(deps)>12 or d['id'] in deps or len(set(deps))!=len(deps):
                raise ValueError('invalid dependencies')
            for dep in deps:
                if not isinstance(dep,str) or db.execute('SELECT 1 FROM task WHERE id=?',(dep,)).fetchone() is None:
                    raise ValueError('missing prerequisite')
            db.execute("BEGIN IMMEDIATE")
            # Atomic enqueue prevents a cloud worker seeing empty instructions.
            # Keep WIP bounded; a lane can queue at most two items at once.
            waiting=db.execute("SELECT COUNT(*) AS n FROM task WHERE id LIKE ? AND state='pending'",
                               (d['lane']+'-%',)).fetchone()['n']
            if waiting >= 2:
                raise ValueError('lane pending WIP limit reached (2)')
            c.add(db,d['id'],'source_inventory',d['paths'],deps,goal=d['goal'],priority=d.get('priority',50))
            db.execute('UPDATE task SET action=? WHERE id=?',(d['instructions'],d['id']))
            db.execute("COMMIT")
            result={'enqueued':d['id']}
        elif args.cmd=='stop':
            db.execute("UPDATE team_meta SET v='stopped' WHERE k='state'")
            c.emit(db,'TEAM','stopped',args.reason);result={'stopped':True}
        else:raise ValueError('unsupported')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    finally:db.close()
if __name__=='__main__':sys.exit(main())

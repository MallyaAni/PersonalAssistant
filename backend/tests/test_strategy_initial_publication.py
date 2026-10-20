"""Canonical approval installation can initialize a reviewed independent snapshot without an account."""
from copy import deepcopy
from datetime import UTC,datetime
import json
from pathlib import Path
import subprocess

import pytest

from backend.cli import market_release_admission as admission
from backend.market import calendar,strategy_publication as publication
from backend.tests.test_market_release_admission import encoded,persist,renewal
from backend.tests.test_strategy_publication import snapshot,signed
from backend.tests.test_strategy_publication_admission import publication_review,ADDED


# Bind a clearly synthetic current snapshot to the actual approval writer and a real temporary Git commit.
def initial_renewal(tmp_path,monkeypatch,*,expired=False):
    root,before,bundle,path,_=renewal(tmp_path,monkeypatch)
    old,new,review=publication_review()
    old_release=json.loads(before['release.json']);old_release['source_sha256']=old
    old_config=json.loads(before['config.json']);old_config['release_receipt_sha256']=admission.digest(encoded(old_release))
    before={**before,'release.json':encoded(old_release),'config.json':encoded(old_config)}
    for name,raw in before.items():(root/admission.CONFIG).with_name(name).write_bytes(raw)
    bundle['predecessor']={name.removesuffix('.json')+'_sha256':admission.digest(raw) for name,raw in before.items()}
    now=datetime.now(UTC);day=calendar.publication_session(now,before=True);assert day is not None
    value=snapshot();value['session']=value['identity']['session']=day.isoformat()
    observed=datetime.combine(day,calendar.session_close(day),calendar.NEW_YORK)
    value['observed_at']=observed.isoformat();value['as_of']=value['published_at']=now.isoformat()
    value['valid_until']=publication.live_model_decision._valid_until(day.isoformat()).isoformat()
    if expired:value['as_of']=value['published_at']=value['observed_at'];value['valid_until']=value['observed_at']
    config=json.loads(bundle['config_json'])
    value['identity'].update(config_sha256=admission.digest(bundle['config_json'].encode()),
        holding_model_receipt_sha256=config['model_receipt_sha256'],risk_receipt_sha256=config['risk_receipt_sha256'],
        timing_config_sha256=config['timing_config_sha256'])
    value['grade_signals']['AAA']['session']=day.isoformat();value['rows']['AAA']['evidence']['inputs_as_of']=day.isoformat()
    value['snapshot_id']=publication._digest(value['identity']);signed(value)
    code=tmp_path/'code';(code/'backend/cli').mkdir(parents=True)
    for name in ADDED:
        target=code/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((Path(admission.__file__).resolve().parents[2]/name).read_bytes())
    relative='docs/research/initial-publication.json';artifact=code/relative;artifact.parent.mkdir(parents=True)
    raw=encoded(value);artifact.write_bytes(raw)
    for argv in (['init','-q'],['config','user.name','Test'],['config','user.email','test@example.invalid'],
        ['add',relative],['commit','-q','-m','Synthetic reviewed publication']):
        subprocess.run(['git','-C',str(code),*argv],check=True,capture_output=True)
    revision=subprocess.check_output(['git','-C',str(code),'rev-parse','HEAD']).decode().strip()
    bundle['target_revision']=revision
    review['initial_publication']={'path':relative,'sha256':admission.digest(raw),'bytes':len(raw)}
    monkeypatch.setattr(admission,'__file__',str(code/'backend/cli/market_release_admission.py'))
    monkeypatch.setattr(admission,'committed_review',lambda *_:deepcopy(review))
    return root,before,bundle,path,review,value,artifact


# Installation makes the exact reviewed model bytes readable immediately and rollback retains evidence.
def test_initial_publication_is_readable_after_approval_without_paper_work(tmp_path,monkeypatch):
    root,before,bundle,path,review,value,artifact=initial_renewal(tmp_path,monkeypatch)
    digest=persist(path,bundle);revision=bundle['target_revision']
    assert admission.preflight(root,path,digest,revision)['status']=='REVIEWED_BUNDLE_ADMITTED'
    assert admission.installed(root)==before and not (root/publication.DIRECTORY).exists()
    receipt=admission.activate(root,path,digest,revision,tmp_path/'archives')
    assert publication.read(root,datetime.now(UTC))==value
    selected=root/publication.DIRECTORY/(value['snapshot_id']+'.json')
    assert selected.read_bytes()==json.dumps(value,sort_keys=True,allow_nan=False).encode()
    original=selected.read_bytes();admission.rollback(root,receipt['archive'])
    assert admission.installed(root)==before and selected.read_bytes()==original


# Rehashed working-copy tampering cannot replace the original committed recommendation.
def test_initial_publication_must_be_the_committed_original(tmp_path,monkeypatch):
    root,before,bundle,path,review,value,artifact=initial_renewal(tmp_path,monkeypatch)
    changed=deepcopy(value);changed['rows']['AAA']['evidence']['features']['ema_21_distance']=.9;signed(changed)
    raw=encoded(changed);artifact.write_bytes(raw)
    review['initial_publication'].update(sha256=admission.digest(raw),bytes=len(raw))
    with pytest.raises(ValueError):admission.preflight(root,path,persist(path,bundle),bundle['target_revision'])
    assert admission.installed(root)==before and not (root/publication.DIRECTORY).exists()


# Original expired clocks cannot be extended merely because a deployment happens later.
def test_initial_publication_expiry_refuses_before_approval_write(tmp_path,monkeypatch):
    root,before,bundle,path,_,_,_=initial_renewal(tmp_path,monkeypatch,expired=True)
    with pytest.raises(ValueError):admission.preflight(root,path,persist(path,bundle),bundle['target_revision'])
    assert admission.installed(root)==before and not (root/publication.DIRECTORY).exists()


# A publication failure restores exact selectors and cannot turn a failed installation into success.
def test_initial_publication_failure_restores_original_approval(tmp_path,monkeypatch):
    root,before,bundle,path,_,_,_=initial_renewal(tmp_path,monkeypatch)
    # Refuse the synthetic persistence step after the normal approval writes.
    def fail(*args,**kwargs):
        raise OSError('synthetic initial publication failure')
    monkeypatch.setattr(publication,'publish',fail)
    with pytest.raises(OSError,match='initial publication failure'):
        admission.activate(root,path,persist(path,bundle),bundle['target_revision'],tmp_path/'archives')
    assert admission.installed(root)==before and len(list((tmp_path/'archives').glob('*/receipt.json')))==1

"""An independent publisher renewal preserves the original strategy and approval selectors."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.cli import market_release_admission as admission
from backend.market import learned_live_holding as runtime
from backend.tests.test_market_release_admission import encoded, persist, renewal

ADDED={f'backend/market/{name}.py' for name in (
    'strategy_model_allocation','strategy_publication','strategy_entry_context','strategy_entries',
    'strategy_reference_transition','strategy_reference_entries','strategy_reference_book',
    'strategy_model_history','strategy_history_installation','strategy_history_publication')}
HOLDING='backend/market/learned_live_holding.py'


# Exercise the separately reviewed current ten-component closure against the original deployed predecessor.
def publication_review():
    new=runtime.source_identity()
    old={name:value for name,value in new.items() if name not in ADDED}
    old[HOLDING]='25fee57bd3dc57c2b945e204aa3b83e39434cf4f84f8a165a4b9e41f9f6183e1'
    review={'status':'REVIEWED_EXACT_OBSERVED_REFERENCE_PUBLICATION',
        'source_changes':{name:{'before_sha256':old.get(name),'after_sha256':new.get(name)} for name in ADDED|{HOLDING}},
        'other_reviewed_sources_unchanged':30,
        'original_holding_module_ast_sha256':'458218fde5e6136cdd44fdf19bf03d4d382a1dc0e3327a6c7b707d315f86c880'}
    return old,new,review


# Activate only reviewed source bindings, read them back, then restore the exact original selectors.
@pytest.mark.xfail(strict=True, reason=(
    'The observed-reference review reconstructs the 41-source holding module exactly; the '
    'grade-led-leader-weight/1 candidate binds two more sources and extends the holding '
    'selector, and the admission CLI refuses a policy change by design, so this transition '
    'is installed by hand (docs/research/trading-approval-candidates-2026-10-21/'
    'leader-weight-policy/README.md) rather than through a new review type'))
def test_publication_renewal_preflight_activation_and_original_rollback(tmp_path,monkeypatch):
    root,before,bundle,path,_=renewal(tmp_path,monkeypatch)
    old,new,review=publication_review()
    release=json.loads(before['release.json']);release['source_sha256']=old
    config=json.loads(before['config.json']);config['release_receipt_sha256']=admission.digest(encoded(release))
    before={**before,'release.json':encoded(release),'config.json':encoded(config)}
    for name,raw in before.items():(root/admission.CONFIG).with_name(name).write_bytes(raw)
    bundle['predecessor']={name.removesuffix('.json')+'_sha256':admission.digest(raw) for name,raw in before.items()}
    monkeypatch.setattr(admission,'committed_review',lambda *_:deepcopy(review))
    digest=persist(path,bundle);revision=bundle['target_revision']
    assert admission.preflight(root,path,digest,revision)['source_sha256']==new
    assert admission.installed(root)==before
    receipt=admission.activate(root,path,digest,revision,tmp_path/'archives')
    after=admission.installed(root)
    assert after['config.json']==bundle['config_json'].encode()
    assert after['release.json']==bundle['release_json'].encode()
    assert after['evidence.json']==before['evidence.json']
    assert admission.check(root)['source_sha256']==new
    admission.rollback(root,receipt['archive'])
    assert admission.installed(root)==before


# Reject every unreviewed source or predecessor mutation instead of broadening the existing guard.
@pytest.mark.parametrize('mutation',('missing_component','extra_component','economic_source','predecessor','review_digest'))
def test_publication_review_rejects_source_drift(mutation):
    old,new,review=publication_review()
    if mutation=='missing_component':new.pop('backend/market/strategy_entries.py')
    elif mutation=='extra_component':new['backend/market/unreviewed.py']='e'*64
    elif mutation=='economic_source':new['backend/market/joint_funded_policy.py']='e'*64
    elif mutation=='predecessor':old[HOLDING]='e'*64
    else:review['source_changes']['backend/market/strategy_entries.py']['after_sha256']='e'*64
    with pytest.raises(ValueError):admission.reviewed_sources(old,new,review)


# Even a rehashed review cannot change the original approval guard or the exact publication callback.
@pytest.mark.parametrize('before,after',(
    ('release["approved"] is not True','release["approved"] is not False'),
    ('publish_prepared(selected, report, clock=clock)','publish_prepared(selected, report, clock=None)'),
))
def test_publication_review_rejects_changed_original_holding(tmp_path,monkeypatch,before,after):
    old,new,review=publication_review()
    raw=Path(runtime.__file__).read_text();assert raw.count(before)==1
    path=tmp_path/'holding.py';path.write_text(raw.replace(before,after))
    new[HOLDING]=admission.digest(path.read_bytes())
    review['source_changes'][HOLDING]['after_sha256']=new[HOLDING]
    monkeypatch.setattr(runtime,'__file__',str(path))
    monkeypatch.setattr(runtime,'source_identity',lambda:new)
    with pytest.raises(ValueError):admission.reviewed_sources(old,new,review)

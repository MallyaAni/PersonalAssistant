"""Canonical deploy ordering for explicitly reviewed historical release data."""
import pytest

from backend.tests.test_deploy_gate_first import Rig,_exe,_missing_tools
from backend.tests.test_deploy_trading_admission import installed

pytestmark=pytest.mark.skipif(bool(_missing_tools()),reason=_missing_tools() or 'tools present')

HISTORY_PYTHON='''#!/usr/bin/env python3
import json,os,pathlib,sys
if sys.argv[1:3]!=['-m','backend.cli.strategy_history_install']:
    os.execv(str(pathlib.Path(__file__).with_name('original-trading-python')),[str(pathlib.Path(__file__).with_name('original-trading-python')),*sys.argv[1:]])
operation=sys.argv[3]
with (pathlib.Path(os.environ['STUB_DIR'])/'order.log').open('a') as stream:stream.write('history-'+operation+'\\n')
if operation=='preflight':sys.exit(int(os.environ.get('HISTORY_PREFLIGHT_EXIT','0')))
if operation=='install':
    if os.environ.get('HISTORY_INSTALL_EXIT')=='1':sys.exit(1)
    path=pathlib.Path(os.environ['DEPLOY_DIR'])/'data/history-selection.json'
    path.write_text('{"original_history":"reviewed"}')
    print(json.dumps({'status':'ORIGINAL_AUDITED_HISTORY_INSTALLED','archive':os.environ['STUB_DIR']+'/history-archive'}))
elif operation=='rollback':
    (pathlib.Path(os.environ['DEPLOY_DIR'])/'data/history-selection.json').unlink()
    print(json.dumps({'status':'ORIGINAL_HISTORY_SELECTION_RESTORED'}))
else:raise AssertionError(operation)
'''


# Retain the existing approval stub while adding a separately identified history installation boundary.
def history_rig(tmp_path):
    rig=Rig(tmp_path);installed(rig)
    original=rig.bin/'trading-python';original.rename(rig.bin/'original-trading-python')
    _exe(original,HISTORY_PYTHON)
    return rig


# A missing digest or refused asset review stops before checkout movement, build or selection writes.
@pytest.mark.parametrize('failure',[{'ANIOS_STRATEGY_HISTORY_REVIEW_SHA256':''},{'HISTORY_PREFLIGHT_EXIT':'1'}])
def test_history_preflight_refusal_preserves_original_release(tmp_path,failure):
    rig=history_rig(tmp_path);rig.push_backend_change()
    configuration={'ANIOS_STRATEGY_HISTORY_REVIEW':'docs/research/history.json','ANIOS_STRATEGY_HISTORY_REVIEW_SHA256':'a'*64,**failure}
    result=rig.run(**configuration)
    assert result.returncode!=0
    assert 'Original audited history assets failed admission.' in result.stderr
    assert rig.head()==rig.first
    assert not (rig.deploy/'data/history-selection.json').exists()
    assert not any(' build ' in row for row in rig.log('docker.log'))


# A successful release actually selects the reviewed history after approval and before restart, then records the release.
def test_history_installation_follows_approval_before_restart(tmp_path):
    rig=history_rig(tmp_path);target=rig.push_backend_change()
    result=rig.run(ANIOS_STRATEGY_HISTORY_REVIEW='docs/research/history.json',ANIOS_STRATEGY_HISTORY_REVIEW_SHA256='a'*64,
        ANIOS_TRADING_APPROVAL_BUNDLE='reviewed.json',ANIOS_TRADING_APPROVAL_BUNDLE_SHA256='b'*64)
    assert result.returncode==0,result.stdout+result.stderr
    order=rig.log('order.log');activate=order.index('activate');history=order.index('history-install')
    restart=next(i for i,row in enumerate(order) if i>history and ' up -d backend' in row)
    assert order.index('history-preflight')<activate<history<restart<order.index('check')
    assert (rig.deploy/'data/history-selection.json').read_text()=='{"original_history":"reviewed"}'
    assert (rig.deploy/'data/.deployed-commit').read_text().strip()==target


# An installation with no returned receipt cannot roll older code over an unknown history selection.
def test_unknown_history_installation_blocks_code_rollback(tmp_path):
    rig=history_rig(tmp_path);target=rig.push_backend_change()
    result=rig.run(ANIOS_STRATEGY_HISTORY_REVIEW='docs/research/history.json',ANIOS_STRATEGY_HISTORY_REVIEW_SHA256='a'*64,HISTORY_INSTALL_EXIT='1')
    assert result.returncode!=0
    assert rig.head()==target
    assert 'HISTORY INSTALLATION OUTCOME UNKNOWN' in result.stderr
    assert (rig.deploy/'data/.deployed-commit').read_text().strip()==rig.first

"""Owner-authorized counterfactual strategy views, separate from live accounts."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi import Path as PathParam

from backend.api.v1.market import _operator_only
from backend.config.settings import settings
from backend.core.auth import authorize_path_user
from backend.market import strategy_research, strategy_history_publication, strategy_entry_history, strategy_replay_sample
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

router = APIRouter(
    prefix="/market/{user_id}/desk/strategy-simulation",
    tags=["market"],
    dependencies=[Depends(authorize_path_user)],
)
UserId = Annotated[str, PathParam(min_length=1, max_length=50)]


# The installed history binds the exact strategy sources it was audited
# against. Once a release changes those sources the sealed reader refuses
# it, and every chart lost its replay the moment the leader-weight policy
# was installed. Until a history is regenerated and installed for the new
# policy, the audited bytes are still the audited bytes: this reads them
# with every byte and accounting check the sealed reader makes, minus the
# binding to the current sources, and says so on the served value, so the
# chart can label the replay by its own policy rather than draw nothing.
def _superseded_history(root, ticker):
    publication = strategy_history_publication
    folder_root = Path(root) / publication.DIRECTORY
    pointer = json.loads(publication._read(folder_root / 'latest.json'))
    identity = publication.publication._sha(pointer['history_sha256'])
    folder = folder_root / identity
    if folder.is_symlink() or folder.resolve().parent != folder_root.resolve():
        raise ValueError('Original history namespace required')
    manifest_raw = publication._read(folder / 'manifest.json')
    audit_raw = publication._read(folder / 'audit.json')
    binding_raw = publication._read(folder / 'binding.json')
    if (sha256(manifest_raw).hexdigest() != identity
            or sha256(audit_raw).hexdigest() != pointer['audit_sha256']
            or sha256(binding_raw).hexdigest() != pointer['binding_sha256']):
        raise ValueError('Original selected history publication differs')
    manifest, audit, binding = json.loads(manifest_raw), json.loads(audit_raw), json.loads(binding_raw)
    if (binding['schema'] != 'strategy-history-economics-binding/1'
            or manifest['counterfactual'] is not True or manifest['real_orders'] is not False
            or audit['status'] != 'VERIFIED_LOCKED_RECOMMENDATION_ACCOUNTING'
            or audit['original_result_sha256'] != binding['history_sha256']):
        raise ValueError('Original audited history accounting differs')
    if ticker is None or ticker not in manifest['files'] or not ticker.isalnum():
        raise ValueError('Original covered history ticker required')
    raw = publication._read(folder / (ticker + '.json'))
    expected = manifest['files'][ticker]
    if len(raw) != expected['bytes'] or sha256(raw).hexdigest() != expected['sha256']:
        raise ValueError('Original stock history bytes differ')
    value = json.loads(raw)
    if (value['ticker'] != ticker or value['policy'] != manifest['policy']
            or value['provenance']['config_sha256'] != binding['config_sha256']
            or value['provenance']['source_record_sha256'] != binding['source_record_sha256']):
        raise ValueError('Original stock provenance differs')
    value['provenance'] = {**value['provenance'], 'strategy_identity': binding['strategy_identity'],
        'strategy_contract': binding, 'verified_against_installed_strategy': False,
        'strategy_binding': 'superseded',
        'grade_clock_basis': 'original_simulated_close_grade_available_at_next_reviewed_open'}
    value['grade_rows'] = [{**row, 'at': publication.next_open(row['date'])} for row in value.get('grade_rows', [])]
    return value


# Serve one authenticated simulation projection without reading or changing a broker.
async def view(user_id, response, ticker=None):
    _operator_only(user_id)
    response.headers["Cache-Control"] = "private, no-store"
    try:
        if (Path(settings.MARKET_DATA_ROOT)/strategy_history_publication.DIRECTORY).exists():
            try:
                value=await asyncio.to_thread(strategy_history_publication.read,settings.MARKET_DATA_ROOT,ticker,datetime.now(UTC))
            except (OSError, ValueError, KeyError, TypeError):
                if ticker is None:
                    raise
                value=await asyncio.to_thread(_superseded_history,settings.MARKET_DATA_ROOT,ticker)
        else:
            value=await asyncio.to_thread(strategy_research.read,settings.MARKET_DATA_ROOT,ticker)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=503, detail="Latest-strategy simulation unavailable."
        ) from exc
    # The frozen-model boundary is stamped on the served rows, not in the sealed
    # artefact, so the chart can mute what the models had already seen.
    return {"user_id": user_id, **strategy_replay_sample.stamp(value), 'recorded_history_version':strategy_entry_history.PAGE_SCHEMA}


# Return the simulated portfolio and dated coverage independently of the paper account.
@router.get("")
async def summary(user_id: UserId, response: Response):
    return await view(user_id, response)


# Return only the requested stock's latest-strategy decisions and simulated trades.
@router.get("/{ticker}")
async def stock(user_id: UserId, ticker: str, response: Response):
    return await view(user_id, response, ticker)


# Restore an original numerical recommendation after expiry, without inferring or reading a funded account.
@router.get('/{ticker}/recommendation')
async def original_recommendation(user_id: UserId, ticker: str, response: Response,
    snapshot_id: Annotated[str, Query(min_length=64,max_length=64)],
    completed_at: Annotated[str, Query(min_length=20,max_length=40)]):
    _operator_only(user_id)
    response.headers['Cache-Control']='private, no-store'
    try:
        value=await asyncio.to_thread(strategy_entry_history.read,settings.MARKET_DATA_ROOT,
            ticker,completed_at,snapshot_id,datetime.now(UTC))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise HTTPException(status_code=503,detail='Original model recommendation unavailable.') from exc
    return {'user_id':user_id,**value}


# Discover original decisions after expiry without inferring, reading an account or substituting current advice.
@router.get('/{ticker}/recommendations')
async def original_recommendations(user_id: UserId, ticker: str, response: Response,
    before: Annotated[str | None, Query(max_length=256)]=None,
    limit: Annotated[int, Query(ge=1,le=strategy_entry_history.MAX_PAGE)]=strategy_entry_history.MAX_PAGE):
    _operator_only(user_id)
    response.headers['Cache-Control']='private, no-store'
    try:
        value=await asyncio.to_thread(strategy_entry_history.recent,settings.MARKET_DATA_ROOT,
            ticker,datetime.now(UTC),before=before,limit=limit)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise HTTPException(status_code=503,detail='Original recorded recommendation history unavailable.') from exc
    return {'user_id':user_id,**value}

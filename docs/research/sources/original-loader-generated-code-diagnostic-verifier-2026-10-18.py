"""SOURCE ONLY independent readback; never import the diagnostic or execute probes."""

import base64
import hashlib
import json
import os
import signal
import sys
import types
from pathlib import Path

SOURCE = Path('/home/animallya96/scratch/n2-generated-code-diagnostic-source-20261018-v1')
RUN = Path('/home/animallya96/scratch/n2-generated-code-diagnostic-20261018-v1')
REVIEW = Path('/home/animallya96/scratch/n2-generated-code-diagnostic-independent-review-20261018-v1')
HELPER = Path('/home/animallya96/scratch/n2-loader-guard-source-20261018-v2/owner/verifier.py')
HELPER_SHA = 'e0fa867a793c78b8260d935ed0c1518f60caa10ba3ab11e084a51ae249ec92f5'


# Fold only retained actual data and a fresh exact-CID inspection, without probe replay.
def verify(self_sha):
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == self_sha
    assert os.getuid() == 1000 and not any(name == 'backend' or name.startswith('backend.') for name in sys.modules)
    raw = HELPER.read_bytes()
    assert len(raw) == 26520 and hashlib.sha256(raw).hexdigest() == HELPER_SHA
    module = types.ModuleType('pinned_diagnostic_readback_only')
    exec(compile(raw, str(HELPER), 'exec', dont_inherit=True), module.__dict__)
    REVIEW.mkdir(mode=0o700, exist_ok=False)
    signal.signal(signal.SIGALRM, module.alarm)
    signal.setitimer(signal.ITIMER_REAL, 30)
    try:
        run_physical, run = module.capture(RUN)
        source_physical, source = module.capture(SOURCE)
        terminal = module.metadata(run['terminal.json'])
        assert terminal['status'] == 'TINY_DIAGNOSTIC_TERMINAL_NOT_GUARD_ACCEPTANCE' and terminal['genuine_or_guard_suite_acceptance'] is False
        book_raw = source['source-book.json']
        book = module.metadata(book_raw)
        assert module.sha(book_raw) == terminal['source_book_sha256']
        retained_source = module.metadata(run['source-before.json'])
        assert retained_source == module.metadata(run['source-after.json'])
        assert set(retained_source) == set(book['files'])
        for name, item in book['files'].items():
            assert source_physical[name]['sha256'] == item['sha256'] and source_physical[name]['bytes'] == item['bytes']
            assert source_physical[name] == retained_source[name]
        admission = module.metadata(source['admission/admission.json'])
        assert module.sha(source['admission/admission.json']) == terminal['admission_sha256']
        assert admission['scope'] == 'TINY_SYNTHETIC_CODE_DIAGNOSTIC_ONLY' and admission['genuine_execution_authorized'] is False
        before = module.metadata(run['prepare-before.json'])
        row, inspect_sha = module.inspect_owned(terminal['cid'], REVIEW, 0)
        binds = [(str(SOURCE / 'audit'), '/audit', False), (str(RUN / 'output'), '/out', True)]
        label = module.sha((str(RUN) + ':' + module.sha(book_raw)).encode())
        name = 'n2-guard-' + label[:20] + '-prepare'
        module.runtime(row, name, label, binds, ['diagnose'], stopped=True)
        assert before['Id'] == row['Id'] and before['Config'] == row['Config']
        assert set(before['HostConfig']) == set(row['HostConfig'])
        differences = {key: [before['HostConfig'][key], row['HostConfig'][key]] for key in before['HostConfig'] if before['HostConfig'][key] != row['HostConfig'][key]}
        assert differences in ({}, {'OomKillDisable': [False, None]})
        assert {item['Destination']: item for item in before['Mounts']} == {item['Destination']: item for item in row['Mounts']}
        expected = {'output/comparison.json'} | {'output/' + mode + '/' + filename for mode in ('deferred', 'live') for filename in ('observation.json', 'terminal.json', 'stdout.log', 'stderr.log')}
        assert {name for name in run if name.startswith('output/')} == expected
        child_ids = []
        for mode in ('deferred', 'live'):
            prefix = 'output/' + mode + '/'
            child = module.metadata(run[prefix + 'terminal.json'])
            assert child['exit'] == 0 and child['owned_stop'] is None and int(child['pid']) > 1
            child_ids.append(child['pid'])
            assert run[prefix + 'stdout.log'] == run[prefix + 'stderr.log'] == b''
        assert len(set(child_ids)) == 2
        deferred = module.metadata(run['output/deferred/observation.json'])
        live = module.metadata(run['output/live/observation.json'])
        frozen = module.metadata(source['audit/frozen-calls.json'])['generated']
        assert module.sha(source['audit/frozen-calls.json']) == 'c8f28b55394b0ef64442f95f021a965dd6ebf1c9b25080f4fcc055a18446fc1e'
        assert deferred['backend_imports_or_Sample_instances'] is live['backend_imports_or_Sample_instances'] is False
        assert deferred['dataclasses_source_sha256'] == live['dataclasses_source_sha256']
        assert live['injected_fence_and_registration'] is True and live['audit_hook_or_failure_slot_or_full_SourceBook'] is False
        fields = {'kind', 'phase', 'module', 'qualname', 'line', 'filename', 'code_sha256', 'producer_source_sha256'}
        for index, item in enumerate(deferred['observations']):
            assert item['ordinal'] == index and set(item['record']) == fields
            encoded = base64.b64decode(item['marshal_base64'], validate=True)
            assert len(encoded) <= 65536 and module.sha(encoded) == item['record']['code_sha256']
            assert item['complete_frozen_matches'] == [number for number, candidate in enumerate(frozen) if candidate == item['record']]
        primary = live['observed_record_computed_by_unchanged_profile']
        if primary is not None:
            assert set(primary) == fields and primary['module'] == 'backend.market.replay_broker'
            assert live['complete_frozen_matches'] == [number for number, item in enumerate(frozen) if item == primary]
        post = base64.b64decode(live['post_observation_marshal_base64'], validate=True)
        assert len(post) <= 65536
        assert live['post_observation_hash_is_primary_record'] == (primary is not None and module.sha(post) == primary['code_sha256'])
        first = deferred['observations'][0]
        comparison = module.metadata(run['output/comparison.json'])
        assert comparison['deferred_first_frozen_reproduced'] == bool(first['complete_frozen_matches'])
        assert comparison['live_refusal_reason'] == live['refusal_reason'] and comparison['live_refusal_identity'] == live['refusal_identity']
        assert comparison['live_complete_frozen_matches'] == live['complete_frozen_matches']
        assert comparison['first_typed_code_content_equal'] == (first['code_content_after_primary_hash'] == live['code_content_after_primary_hash'])
        calculated = None if primary is None else [{key: [item['record'][key], primary[key]] for key in fields if item['record'][key] != primary[key]} for item in deferred['observations']]
        assert calculated == comparison['live_vs_every_deferred_record_differences']
        assert comparison['original_failed_guard_hash_recovered'] is comparison['genuine_or_guard_suite_acceptance'] is False
        assert module.sha(run['output/comparison.json']) == terminal['comparison_sha256']
        assert module.capture(RUN)[0] == run_physical and module.capture(SOURCE)[0] == source_physical
        report = {'status': 'TINY_DIAGNOSTIC_READBACK_ONLY', 'self_sha256': self_sha, 'runtime_inspect_sha256': inspect_sha,
                  'actual_runtime': row, 'created_to_stopped_HostConfig_differences': differences, 'child_ids': child_ids,
                  'comparison': comparison, 'run_physical': run_physical, 'source_physical': source_physical,
                  'test_bodies_reexecuted': 0, 'genuine_or_guard_suite_acceptance': False}
        encoded = json.dumps(report, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
        assert len(encoded) <= 262144
        with (REVIEW / 'proof.json').open('xb') as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        assert (REVIEW / 'proof.json').read_bytes() == encoded
        descriptor = os.open(REVIEW, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        print(json.dumps({'proof_sha256': module.sha(encoded), 'proof_bytes': len(encoded), 'comparison': comparison}, sort_keys=True), flush=True)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


# Refuse ordinary execution until an exact independent verifier source pin is supplied.
def main(arguments):
    if len(arguments) != 2 or arguments[0] != '--readback-only':
        raise SystemExit('SOURCE_ONLY_NO_DIAGNOSTIC_READBACK')
    verify(arguments[1])


if __name__ == '__main__':
    main(sys.argv[1:])

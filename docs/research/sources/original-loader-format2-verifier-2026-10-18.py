"""SOURCE ONLY independent readback; never import the diagnostic or execute probes."""

import base64
import hashlib
import json
import os
import signal
import sys
import types
from pathlib import Path

SOURCE = Path('/home/animallya96/scratch/n2-format2-hypothesis-source-20261018-v1')
RUN = Path('/home/animallya96/scratch/n2-format2-hypothesis-20261018-v1')
REVIEW = Path('/home/animallya96/scratch/n2-format2-hypothesis-independent-review-20261018-v1')
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
        assert terminal['status'] == 'FORMAT2_TERMINAL_NOT_GUARD_ACCEPTANCE' and terminal['genuine_or_guard_suite_acceptance'] is False
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
        assert admission['scope'] == 'TINY_SYNTHETIC_FORMAT2_HYPOTHESIS_ONLY' and admission['genuine_execution_authorized'] is False
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
        expected = {'output/comparison.json'} | {'output/' + mode + '/' + filename for mode in ('prepare', 'controls') for filename in ('observation.json', 'terminal.json', 'stdout.log', 'stderr.log')}
        assert {name for name in run if name.startswith('output/')} == expected
        child_ids = []
        for mode in ('prepare', 'controls'):
            prefix = 'output/' + mode + '/'
            child = module.metadata(run[prefix + 'terminal.json'])
            assert child['exit'] == 0 and child['owned_stop'] is None and int(child['pid']) > 1
            child_ids.append(child['pid'])
            assert run[prefix + 'stdout.log'] == run[prefix + 'stderr.log'] == b''
        assert len(set(child_ids)) == 2
        prepared = module.metadata(run['output/prepare/observation.json'])
        controls = module.metadata(run['output/controls/observation.json'])
        manifest = prepared['candidate_manifest']
        assert manifest['schema'] == 'tiny-generated-code-format2-candidate/1'
        assert manifest['fingerprint_algorithm'] == 'cpython-code-marshal-format-2-sha256/1'
        assert type(manifest['marshal_version']) is int and manifest['marshal_version'] == 2
        assert manifest['python'] == controls['python'] and prepared['first_wrapper_is_module'] is True
        assert manifest['tiny_source_sha256'] == '1247f21782dae095b2028e24d8c8039cb47440ebe7470a4c9cb7c32758a776da'
        assert manifest['producer_source_sha256'] == 'd242aea5fcf6408b1c1f622442f88f68b9526ce1f8bd2890d74a144677c427d9'
        fields = {'kind', 'phase', 'module', 'qualname', 'line', 'filename', 'code_sha256', 'producer_source_sha256'}
        rows = manifest['generated']
        assert len(rows) == 7 and len({json.dumps(item, sort_keys=True) for item in rows}) == 7
        for item in rows:
            assert set(item) == fields and item['phase'] == 'BOOTSTRAP' and item['module'] == 'backend.market.replay_broker'
            assert item['producer_source_sha256'] == manifest['producer_source_sha256'] and item['filename'] == '<string>'
        raw_wrapper = base64.b64decode(prepared['first_wrapper_raw_base64'], validate=True)
        assert len(raw_wrapper) <= 65536 and module.sha(raw_wrapper) == rows[0]['code_sha256'] and rows[0]['qualname'] == '<module>'
        expected_cases = ['positive-format2'] + ['wrong-' + field for field in sorted(fields)] + ['changed-bytecode', 'changed-constant']
        assert [item['case'] for item in controls['cases']] == expected_cases
        for index, case in enumerate(controls['cases']):
            actual = case['actual']
            assert len(actual['hash_observations']) == 1
            observed = actual['hash_observations'][0]
            assert set(observed['record']) == fields
            body = base64.b64decode(observed['raw_base64'], validate=True)
            assert len(body) <= 65536 and module.sha(body) == observed['record']['code_sha256']
            expected = {'reason': 'BROKER_OR_ACCOUNT_FUNCTION', 'identity': 'backend.market.replay_broker.__create_fn__'} if index == 0 else {'reason': 'UNREVIEWED_GENERATED_CODE', 'identity': 'backend.market.replay_broker.<module>'}
            assert actual['refusal'] == expected
            if index < 9:
                assert observed['record'] == rows[0] and body == raw_wrapper and actual['registered_calls_seen'] == 2
            else:
                assert body != raw_wrapper and observed['record']['code_sha256'] != rows[0]['code_sha256']
                assert {key: value for key, value in observed['record'].items() if key != 'code_sha256'} == {key: value for key, value in rows[0].items() if key != 'code_sha256'}
                assert actual['registered_calls_seen'] == 0
        assert controls['schema_controls'] == [
            {'field': 'schema', 'value': 'n2-capacity-call-manifest/1', 'rejected_before_live': True},
            {'field': 'fingerprint_algorithm', 'value': 'implicit-default-marshal', 'rejected_before_live': True},
            {'field': 'marshal_version', 'value': 4, 'rejected_before_live': True},
            {'field': 'marshal_version', 'value': True, 'rejected_before_live': True}]
        assert controls['scope'] == 'INJECTED_FORMAT2_ADAPTER_NOT_FULL_GUARD_ACCEPTANCE'
        assert controls['guard_modified'] is controls['original_failure_hash_recovered'] is False and controls['Sample_instances'] == 0
        comparison = module.metadata(run['output/comparison.json'])
        assert comparison == {'status': 'FORMAT2_HYPOTHESIS_CONTROLS_COMPLETE',
            'candidate_schema': manifest['schema'], 'fingerprint_algorithm': manifest['fingerprint_algorithm'],
            'marshal_version': 2, 'first_wrapper_raw_bytes_equal': True, 'profile_cases': 11,
            'version_controls': 4, 'genuine_or_guard_suite_acceptance': False}
        assert module.sha(run['output/comparison.json']) == terminal['comparison_sha256']
        assert module.capture(RUN)[0] == run_physical and module.capture(SOURCE)[0] == source_physical
        report = {'status': 'FORMAT2_HYPOTHESIS_READBACK_ONLY', 'self_sha256': self_sha, 'runtime_inspect_sha256': inspect_sha,
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
        raise SystemExit('SOURCE_ONLY_NO_FORMAT2_READBACK')
    verify(arguments[1])


if __name__ == '__main__':
    main(sys.argv[1:])

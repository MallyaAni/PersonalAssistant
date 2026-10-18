"""SOURCE ONLY independent readback; never import the diagnostic or execute probes."""

import base64
import hashlib
import json
import os
import signal
import sys
import types
from pathlib import Path

SOURCE = Path('/home/animallya96/scratch/n2-guard-v3-tiny-source-20261018-v1')
RUN = Path('/home/animallya96/scratch/n2-guard-v3-tiny-20261018-v1')
REVIEW = Path('/home/animallya96/scratch/n2-guard-v3-tiny-independent-review-20261018-v1')
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
        assert terminal['status'] == 'V3_TINY_TERMINAL_NOT_FULL_GUARD_ACCEPTANCE' and terminal['genuine_or_guard_suite_acceptance'] is False
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
        assert admission['scope'] == 'TINY_SYNTHETIC_V3_ACTUAL_FENCE_ONLY' and admission['genuine_execution_authorized'] is False
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
        prepared = module.metadata(run['output/prepare/prepared/summary.json'])
        assert prepared['scope'] == 'INJECTED_TINY_RECIPE_NOT_GENUINE2446'
        assert prepared['harness_sha256'] == '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
        assert prepared['dataclasses_source_sha256'] == 'd242aea5fcf6408b1c1f622442f88f68b9526ce1f8bd2890d74a144677c427d9'
        manifest = module.metadata(run['output/prepare/prepared/calls.json'])
        assert module.sha(run['output/prepare/prepared/calls.json']) == prepared['calls_sha256']
        assert manifest['schema'] == 'n2-capacity-call-manifest/2'
        assert manifest['fingerprint'] == {'algorithm': 'cpython-code-marshal-format-2-sha256/1', 'marshal_version': 2}
        assert type(manifest['fingerprint']['marshal_version']) is int and len(manifest['generated']) == 16
        before_prepared = module.metadata(run['output/prepared-before.json'])
        assert before_prepared == module.metadata(run['output/prepared-after.json']) and len(before_prepared) == 8
        for name, identity in before_prepared.items():
            assert run_physical['output/prepare/prepared/' + name] == identity
        for name, checksum in prepared['pins'].items():
            assert run_physical['output/prepare/prepared/source/' + name]['sha256'] == checksum
        expectations = [
            ('dataclass-positive', 0, None, None),
            ('broker-effect', 86, 'BROKER_OR_ACCOUNT_FUNCTION', 'backend.market.replay_broker.__create_fn__')]
        fields = ('kind', 'phase', 'module', 'qualname', 'line', 'filename', 'code_sha256', 'producer_source_sha256')
        for field in fields:
            reason = 'EXACT_DAILY_PREFIX_RECORD_REQUIRED' if field == 'kind' else 'EXACT_DATACLASS_FILENAME_REQUIRED' if field == 'filename' else 'UNREVIEWED_GENERATED_CODE'
            expectations.append(('binding-' + field, 1 if field in ('kind', 'filename') else 86, reason, None if field in ('kind', 'filename') else 'backend.capacity_dataclass.<module>'))
        for label in ('changed-bytecode', 'changed-constant'):
            expectations.append((label, 86, 'UNREVIEWED_GENERATED_CODE', 'backend.capacity_dataclass.<module>'))
        expectations.append(('prefix-positive', 0, None, None))
        for label in ('wrapper', 'inputs', 'producer', 'phase'):
            expectations.append(('prefix-' + label, 86, 'UNREGISTERED_OR_GENERATED_CODE' if label == 'phase' else 'UNREVIEWED_GENERATED_CODE', 'backend.cli.market_strategy_continue.' + ('inputs' if label == 'inputs' else '<module>')))
        for label, reason in (('schema-old', 'CALL_MANIFEST_BINDING_DIFFERS'), ('schema-missing-fingerprint', 'EXACT_CALL_MANIFEST_REQUIRED'), ('algorithm', 'GENERATED_FINGERPRINT_BINDING_DIFFERS'), ('version', 'GENERATED_FINGERPRINT_BINDING_DIFFERS'), ('bool-version', 'GENERATED_FINGERPRINT_BINDING_DIFFERS')):
            expectations.append((label, 1, reason, None))
        assert len(expectations) == 22 and prepared['scenario_ids'] == [item[0] for item in expectations]
        comparison = module.metadata(run['output/comparison.json'])
        assert comparison['status'] == 'V3_TINY_ACTUAL_FENCE_COMPLETE' and comparison['case_count'] == 22
        assert comparison['marshal_adapter'] is comparison['genuine_or_full_guard_suite_acceptance'] is False
        assert comparison['injected_recipe_not_genuine2446'] is True
        assert comparison['candidate_harness_sha256'] == prepared['harness_sha256']
        assert [item['id'] for item in comparison['cases']] == prepared['scenario_ids']
        child_ids = []
        first = module.metadata(run['output/prepare/terminal.json'])
        assert first['exit'] == 0 and first['owned_stop'] is None and int(first['pid']) > 1
        child_ids.append(first['pid'])
        assert run['output/prepare/stdout.log'] == run['output/prepare/stderr.log'] == b''
        for (label, code, reason, identity), outcome in zip(expectations, comparison['cases'], strict=True):
            prefix = 'output/cases/' + label + '/'
            child = module.metadata(run[prefix + 'terminal.json'])
            assert child['exit'] == outcome['exit'] == code and child['pid'] == outcome['pid'] and child['owned_stop'] is None and int(child['pid']) > 1
            child_ids.append(child['pid'])
            assert run[prefix + 'stdout.log'] == run[prefix + 'stderr.log'] == b''
            old_slot = module.metadata(run[prefix + 'slot-before.json'])
            actual_slot = run_physical[prefix + 'failure.bin']
            assert outcome['slot_after'] == actual_slot['physical'] and outcome['slot_sha256'] == actual_slot['sha256']
            assert all(old_slot[key] == actual_slot['physical'][key] for key in old_slot if key not in ('st_mtime_ns', 'st_ctime_ns'))
            assert actual_slot['bytes'] == 65536 and int(actual_slot['physical']['st_blocks']) * 512 >= 65536
            body = run[prefix + 'failure.bin']
            names = {name[len(prefix):] for name in run if name.startswith(prefix)}
            required = {'failure.bin', 'manifest.json', 'slot-before.json', 'stdout.log', 'stderr.log', 'terminal.json'}
            if code == 86:
                raw_failure = body.rstrip(bytes((0,)))
                phase = 'LOAD' if label.startswith('prefix-') and label != 'prefix-phase' else 'BOOTSTRAP'
                assert module.metadata(raw_failure) == {'status': 'FAILED_CLOSED', 'phase': phase, 'reason': reason, 'identity': identity, 'publication': 'CLOSED'}
                assert body == raw_failure + bytes(65536 - len(raw_failure))
            elif code == 1:
                assert body == bytes(65536)
                assert module.metadata(run[prefix + 'constructor-refusal.json']) == {'reason': reason, 'backend_modules': []}
                required.add('constructor-refusal.json')
            else:
                assert body == bytes(65536)
                returned = module.metadata(run[prefix + 'returned.json'])
                assert returned['marshal_adapter'] is returned['genuine_admission'] is False
                assert returned['injected_recipe'] is returned['actual_candidate_constructor_profile_audit'] is True
                marker = 'prefix.marker' if label == 'prefix-positive' else 'dataclass.marker'
                assert run[prefix + marker] == (b'FIRST_DEPENDENCY_BEFORE_DATA' if label == 'prefix-positive' else b'TINY_SAMPLE_VALUE_3')
                assert returned['phase'] == ('LOAD' if label == 'prefix-positive' else 'BOOTSTRAP')
                required.update({'returned.json', marker})
            assert names == required
        assert len(set(child_ids)) == 23
        assert module.sha(run['output/comparison.json']) == terminal['comparison_sha256']
        assert module.capture(RUN)[0] == run_physical and module.capture(SOURCE)[0] == source_physical
        report = {'status': 'V3_TINY_ACTUAL_FENCE_READBACK_ONLY', 'self_sha256': self_sha, 'runtime_inspect_sha256': inspect_sha,
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
        raise SystemExit('SOURCE_ONLY_NO_V3_TINY_READBACK')
    verify(arguments[1])


if __name__ == '__main__':
    main(sys.argv[1:])

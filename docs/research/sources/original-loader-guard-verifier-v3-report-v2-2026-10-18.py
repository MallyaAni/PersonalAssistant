"""UNEXECUTED independent verifier for one proposed synthetic guard run.

This file imports no fixture, suite, harness, application or numerical module.
It checks frozen expected cases against actual stopped Docker records, complete
physical files and exact child exit/marker evidence. It cannot admit a genuine
source tree, loader, model capacity, account or historical publication.
"""

import base64
import hashlib
import json
import os
import resource
import signal
import stat
import subprocess
from pathlib import Path

IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
FINGERPRINT = {'algorithm': 'cpython-code-marshal-format-2-sha256/1', 'marshal_version': 2}
HARNESS_SHA = '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
MANIFEST_SCHEMA = 'n2-capacity-call-manifest/2'

PHASES = ('BOOTSTRAP', 'ADMISSION', 'BEFORE', 'LOAD', 'FROZEN', 'AFTER', 'SERIALIZE', 'DONE')


# Refuse duplicate metadata without silently replacing an earlier field.
def unique(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result
        result[key] = value
    return result


# Refuse nonfinite raw JSON tokens in acceptance metadata.
def nonfinite(value):
    raise ValueError('NONFINITE_VERIFIER_METADATA')


# Parse finite duplicate-free bounded metadata independently of the harness.
def metadata(raw):
    assert len(raw) <= 2 * 1024 ** 2
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


# Name whole retained files without changing their byte representation.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Retain exact physical counters as decimal strings, including nanoseconds.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Make the independent fold's actual wall deadline interrupt bounded owned waits.
def alarm(signum, frame):
    raise KeyboardInterrupt('INDEPENDENT_VERIFIER_WALL_DEADLINE')


# Bound the independent Docker client's log files without claiming daemon quotas.
def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    os.nice(10)


# Read a fresh exact CID independently, always retaining CLI terminal evidence.
def inspect_owned(cid, review_root, index):
    assert len(cid) == 64 and all(char in '0123456789abcdef' for char in cid)
    prefix = 'inspect-' + str(index)
    stdout = (review_root / (prefix + '.stdout')).open('xb')
    stderr = (review_root / (prefix + '.stderr')).open('xb')
    environment = dict(os.environ)
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        environment.pop(key, None)
    process, stopped = None, None
    try:
        prior = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        try:
            process = subprocess.Popen(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'inspect', '--type=container', cid], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, env=environment, preexec_fn=limits)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, prior)
        process.wait(timeout=10)
    finally:
        if process is not None and process.poll() is None:
            stopped = 'TERM'
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                stopped = 'KILL'
                process.kill()
                process.wait(timeout=1)
        stdout.flush()
        stderr.flush()
        os.fsync(stdout.fileno())
        os.fsync(stderr.fileno())
        stdout.close()
        stderr.close()
        record = {'pid': None if process is None else str(process.pid), 'exit': None if process is None else process.returncode, 'owned_stop': stopped, 'cid': cid}
        with (review_root / (prefix + '.exit.json')).open('xb') as output:
            output.write(json.dumps(record, sort_keys=True).encode())
            output.flush()
            os.fsync(output.fileno())
    raw = (review_root / (prefix + '.stdout')).read_bytes()
    assert process.returncode == 0 and stopped is None and (review_root / (prefix + '.stderr')).read_bytes() == b''
    rows = metadata(raw)
    assert type(rows) is list and len(rows) == 1 and rows[0]['Id'] == cid
    return rows[0], sha(raw)


# Capture bounded no-follow regular files with held-FD/path identity bookends.
def capture(root):
    assert root.resolve(strict=True) == root and root.is_dir() and root.stat().st_uid == 1000
    result, bodies, total = {}, {}, 0
    pending = [root]
    while pending:
        directory = pending.pop()
        before = directory.stat(follow_symlinks=False)
        assert stat.S_ISDIR(before.st_mode) and before.st_uid == 1000
        for path in sorted(directory.iterdir()):
            value = path.stat(follow_symlinks=False)
            if stat.S_ISLNK(value.st_mode):
                # Only deliberate G05 links in private fixture copies are legal.
                relative = str(path.relative_to(root))
                allowed = ('G05-root-link/root-link', 'G05-middle-link/source/backend', 'G05-file-link/source/backend/capacity_fixture.py')
                assert relative in allowed or relative in tuple('suite-output/suite/' + name for name in allowed)
                result[relative] = {'symlink': os.readlink(path), 'physical': physical(value)}
                continue
            if stat.S_ISDIR(value.st_mode):
                assert len(pending) < 4096
                pending.append(path)
                continue
            assert stat.S_ISREG(value.st_mode) and value.st_uid == 1000
            relative = str(path.relative_to(root))
            limit = 2 * 1024 ** 2 if path.name == 'packet.json' else 262144
            if relative in ('G05-grow/source/backend/capacity_fixture.py', 'suite-output/suite/G05-grow/source/backend/capacity_fixture.py'):
                limit = 1048577 + 4096
            assert value.st_size <= limit and len(result) < 4096
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                held = os.fstat(descriptor)
                chunks = []
                length = 0
                while block := os.read(descriptor, min(65536, limit + 1 - length)):
                    length += len(block)
                    assert length <= limit
                    chunks.append(block)
                raw = b''.join(chunks)
                assert physical(held) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False)) == physical(value)
            finally:
                os.close(descriptor)
            total += len(raw)
            assert total <= 64 * 1024 ** 2
            relative = str(path.relative_to(root))
            result[relative] = {'physical': physical(value), 'sha256': sha(raw), 'bytes': len(raw)}
            bodies[relative] = raw
        assert physical(before) == physical(directory.stat(follow_symlinks=False))
    return result, bodies


# Declare every expected case independently of the runner's assessment logic.
def cases():
    groups = (
        ('G01', ['positive']), ('G02', ['alias']), ('G03', ['import-call']),
        ('G04', ['missing', 'shadow', 'pyc']),
        ('G05', ['root-link', 'middle-link', 'file-link', 'tamper', 'replace', 'grow']),
        ('G06', ['manifest-sha', 'manifest-schema', 'manifest-duplicate', 'manifest-nan']),
        ('G07', ['distribution', 'select', 'fit', 'submit_order', 'audit', 'stateful']),
        ('G08', ['effect-function', 'effect-generated']),
        ('G09', ['generated-positive', 'generated-code', 'generated-producer']),
        ('G10', ['prefix-positive', 'prefix-wrapper', 'prefix-inputs', 'prefix-producer', 'prefix-phase']),
        ('G11', ['catch']), ('G12', ['profile', 'trace', 'thread', 'socket', 'process']),
        ('G13', ['readonly', 'append', 'sparse', 'size', 'link', 'nonzero', 'path']),
        ('G14', ['no-fence', 'no-finder', 'no-auth']),
        ('G15', ['runtime', 'profile', 'mapping', 'version', 'runtime-duplicate', 'runtime-nan', 'invocation-duplicate', 'runtime-hash', 'invocation-hash']),
        ('G16', ['journey']),
        ('G17', ['receipt', 'state', 'nan', 'collision', 'source', 'inventory-growth', 'output-growth']),
    )
    return [{'id': group + '-' + variant, 'group': group, 'variant': variant} for group, variants in groups for variant in variants]


# Bind each ordinary refusal to its specific first failing boundary.
def error_token(case):
    group, variant = case['group'], case['variant']
    if group == 'G04':
        return 'EXACT_BACKEND_MODULE_REQUIRED'
    if group == 'G05':
        return {'root-link': 'Not a directory', 'middle-link': 'Not a directory', 'file-link': 'Too many levels', 'tamper': 'SOURCE_BYTES_DIFFER', 'replace': 'SOURCE_CHANGED_SINCE_ADMISSION', 'grow': 'BOUNDED_REGULAR_SOURCE_REQUIRED'}[variant]
    if group == 'G06':
        return {'manifest-sha': 'EXTERNALLY_PINNED_CALL_MANIFEST_REQUIRED', 'manifest-schema': 'CALL_MANIFEST_BINDING_DIFFERS', 'manifest-duplicate': 'DUPLICATE_METADATA_FIELD', 'manifest-nan': 'NONFINITE_METADATA_TOKEN'}[variant]
    if group == 'G13':
        return {'readonly': 'READWRITE_NONAPPEND_FAILURE_SLOT_REQUIRED', 'append': 'READWRITE_NONAPPEND_FAILURE_SLOT_REQUIRED', 'sparse': 'PREALLOCATED_FAILURE_SLOT_REQUIRED', 'size': 'PREALLOCATED_FAILURE_SLOT_REQUIRED', 'link': 'PREALLOCATED_FAILURE_SLOT_REQUIRED', 'nonzero': 'FAILURE_SLOT_NOT_EMPTY', 'path': 'RESERVED_FAILURE_FD_PATH_DIFFERS'}[variant]
    if group == 'G14':
        return {'no-fence': 'PREIMPORT_CALL_GUARD_REQUIRED', 'no-finder': 'PINNED_IMPORT_FINDER_MUST_BE_FIRST', 'no-auth': 'COMPLETE_SOURCE_ADMISSION_REQUIRED'}[variant]
    if group == 'G15':
        return {'runtime': 'EXACT_ORIGINAL_AUDITOR_REQUIRED', 'profile': 'EXACT_ORIGINAL_AUDITOR_REQUIRED', 'mapping': 'EXACT_ORIGINAL_ACCOUNT_MAPPING_REQUIRED', 'version': 'EXACT_NATIVE_PACKAGES_REQUIRED', 'runtime-duplicate': 'DUPLICATE_METADATA_FIELD', 'runtime-nan': 'NONFINITE_METADATA_TOKEN', 'invocation-duplicate': 'DUPLICATE_METADATA_FIELD', 'runtime-hash': 'EXTERNAL_RUNTIME_BYTES_REQUIRED', 'invocation-hash': 'EXTERNAL_INVOCATION_BYTES_REQUIRED'}[variant]
    return {'receipt': 'COMPLETE_BYTE_RECEIPTS_CHANGED', 'state': 'ORIGINAL_STATE_CHANGED', 'nan': 'Out of range float', 'collision': 'File exists', 'source': 'SOURCE_BYTES_DIFFER', 'inventory-growth': 'RETAINED_STACK_BOUND', 'output-growth': 'CAPACITY_RESULT_BOUND_EXCEEDED'}[variant]


# Determine only the expected observed guard reason, never infer it from nonzero.
def guard_reasons(case):
    group, variant = case['group'], case['variant']
    if group in ('G02', 'G03', 'G11'):
        return {'UNREVIEWED_PHASE_CALL'}
    if group == 'G07':
        return {'FORBIDDEN_STATEFUL_CLASS'} if variant == 'stateful' else {'FORBIDDEN_FUNCTION'}
    if group == 'G08':
        return {'BROKER_OR_ACCOUNT_FUNCTION'}
    if group == 'G09' and variant != 'generated-positive':
        return {'UNREVIEWED_GENERATED_CODE'}
    if group == 'G10' and variant != 'prefix-positive':
        return {'UNREGISTERED_OR_GENERATED_CODE'} if variant == 'prefix-phase' else {'UNREVIEWED_GENERATED_CODE'}
    if group == 'G12':
        return {'PROFILE_REPLACEMENT', 'PROFILE_OR_TRACE_REPLACEMENT'} if variant == 'profile' else {'PROFILE_OR_TRACE_REPLACEMENT'} if variant == 'trace' else {'UNADMITTED_PYTHON_THREAD'} if variant == 'thread' else {'FORBIDDEN_AUDIT_EVENT'}
    return set()


# Check exact runtime placement/resources/commands against observed Docker bytes.
def runtime(row, name, label, binds, command, stopped):
    host, config, state = row['HostConfig'], row['Config'], row['State']
    assert row['Name'] == '/' + name and len(row['Id']) == 64 and row['Image'] == IMAGE
    assert config['Labels']['anios.synthetic.guard-owner'] == label and config['User'] == '1000:1000'
    assert config['Entrypoint'] == ['python'] and config['Cmd'] == ['-I', '-S', '-B', '/audit/bootstrap.py'] + command
    assert host['NetworkMode'] == 'none' and host['ReadonlyRootfs'] is True and host['NanoCpus'] == 1000000000
    assert host['Memory'] == host['MemorySwap'] == 2147483648 and host['PidsLimit'] == 32
    assert host['Tmpfs'] == {'/tmp': 'rw,size=64m'} and host['Privileged'] is False and not host['Devices'] and not host['CapAdd']
    assert host['CapDrop'] == ['ALL'] and 'no-new-privileges:true' in host['SecurityOpt']
    assert host['LogConfig']['Type'] == 'none' and config['Healthcheck']['Test'] == ['NONE']
    assert {(item['Source'], item['Destination'], item['RW']) for item in row['Mounts']} == set(binds)
    assert len(row['Mounts']) == len(binds)
    assert state['Running'] is False and state['OOMKilled'] is False
    assert state['ExitCode'] == 0 and state['Status'] == ('exited' if stopped else 'created')


# Validate real kernel measurement shapes and actual retained phase ordering.
def measurements(raws):
    expected = ['ADMISSION', 'BEFORE', 'FROZEN', 'AFTER', 'SERIALIZED_WITH_BOTH_RECEIPTS_AND_LOADED_CONTEXT']
    rows = [metadata(raw) for raw in raws]
    assert [row['phase'] for row in rows] == expected[:len(rows)]
    assert all(type(row['monotonic']) in (int, float) for row in rows)
    assert all(left['monotonic'] < right['monotonic'] for left, right in zip(rows, rows[1:]))
    for row in rows:
        assert type(row['ru_maxrss_kib']) is int and row['ru_maxrss_kib'] > 0
        rss, hwm = (int(row[key].split()[0]) for key in ('VmRSS', 'VmHWM'))
        assert 0 < rss <= hwm and row['VmRSS'].endswith('kB') and row['VmHWM'].endswith('kB')
        counter = row['cgroup']
        assert 0 < int(counter['memory.current']) <= int(counter['memory.peak']) <= 2147483648
        assert counter['memory.swap.current'] == '0'
        events = dict(line.split() for line in counter['memory.events'].splitlines())
        assert events['oom'] == events['oom_kill'] == '0'
    return rows


# Inspect every actual child marker, fixed failure slot and specific outcome.
def child(case, inventory, bodies, base_fixture):
    prefix = case['id'] + '/'
    terminal = metadata(bodies[prefix + 'terminal.json'])
    assert terminal['owned_stop'] is None and int(terminal['pid']) > 1
    assert bodies[prefix + 'stdout.log'] == bodies[prefix + 'stderr.log'] == b''
    assert prefix + 'proof/forbidden.marker' not in inventory and prefix + 'proof/caught.marker' not in inventory
    reasons = guard_reasons(case)
    slot_name = prefix + 'proof/guard-failure.bin'
    raw_slot = bodies[slot_name]
    if reasons:
        assert terminal['returncode'] == 86 and len(raw_slot) == 65536
        failure = metadata(raw_slot.rstrip(b'\0'))
        assert failure['reason'] in reasons and failure['status'] == 'FAILED_CLOSED' and failure['publication'] == 'CLOSED'
        assert prefix + 'returned.json' not in bodies and prefix + 'error.json' not in bodies
        if case['id'] == 'G08-effect-generated':
            assert '__create_fn__' in failure['identity']
        return terminal
    positive = case['id'] in ('G01-positive', 'G09-generated-positive', 'G10-prefix-positive', 'G16-journey')
    if positive:
        assert terminal['returncode'] == 0 and raw_slot == bytes(65536)
        returned = metadata(bodies[prefix + 'returned.json'])
        assert returned['case'] == case['id'] and returned['status'] == 'SYNTHETIC_RETURNED'
        if case['group'] == 'G01':
            assert bodies[prefix + 'proof/safe.marker'] == b'safe'
        if case['group'] == 'G10':
            assert bodies[prefix + 'proof/prefix-dependency.marker'] == b'stopped-before-data'
        if case['group'] == 'G16':
            destination = prefix + 'proof/original-loader-capacity/'
            candidate = metadata(bodies[destination + 'candidate.json'])
            assert candidate['historical_publication_authorized'] is False and candidate['account_or_orders'] is False
            assert candidate['risk_bank_rows'] == candidate['full_fixed_calibration_dates'] == 3
            assert candidate['runtime']['status'] == 'INJECTED_SYNTHETIC_NOT_RUNTIME_ADMISSION'
            assert len(candidate['retained_arrays']) == 1 and candidate['retained_arrays'][0]['view_nbytes'] == '2'
            for index in (1, 2):
                coexist = metadata(bodies[prefix + 'proof/coexist-' + str(index) + '.json'])
                assert coexist['loaded_alive'] is True and coexist['distinct_receipts'] is True
                assert coexist['has_serialized'] == coexist['has_encoded'] == (index == 2)
                assert metadata(bodies[prefix + 'proof/auth-' + str(index) + '.json']) == {'synthetic': True}
            assert metadata(bodies[prefix + 'proof/load.json']) == {'synthetic': True}
            measurements([bodies[destination + 'phase-' + str(i) + '.json'] for i in range(1, 6)])
        return terminal
    assert terminal['returncode'] == 1 and prefix + 'returned.json' not in bodies
    error = metadata(bodies[prefix + 'error.json'])
    assert error_token(case) in error['message']
    group, variant = case['group'], case['variant']
    if group == 'G13' and variant == 'size':
        assert raw_slot == bytes(65535)
    elif group == 'G13' and variant == 'nonzero':
        assert raw_slot == b'x' + bytes(65535)
    else:
        assert raw_slot == bytes(65536)
    if group == 'G13' and variant == 'sparse':
        assert int(inventory[slot_name]['physical']['st_blocks']) * 512 < 65536
    if group == 'G13' and variant == 'link':
        linked = prefix + 'extra-link'
        assert bodies[linked] == raw_slot and inventory[linked]['physical']['st_ino'] == inventory[slot_name]['physical']['st_ino']
        assert inventory[slot_name]['physical']['st_nlink'] == '2'
    if group in ('G04', 'G05', 'G06', 'G14') or (group == 'G13' and variant != 'path') or (group == 'G15' and variant != 'version'):
        assert 'backend.cli.audit_original_live_model_history' not in error['backend_modules']
    if group == 'G13' and variant == 'path':
        held = prefix + 'held-original-slot.bin'
        assert bodies[held] == raw_slot == bytes(65536)
        assert inventory[held]['physical']['st_ino'] != inventory[slot_name]['physical']['st_ino']
    if case['id'] == 'G05-grow':
        assert len(base_fixture) <= 4096
        oversized_name = prefix + 'source/backend/capacity_fixture.py'
        oversized = bodies[oversized_name]
        assert oversized == base_fixture + bytes(1048577)
        growth = metadata(bodies[prefix + 'growth.json'])
        assert growth['sha256'] == sha(oversized) and growth['bytes'] == len(oversized)
        assert growth['inode'] == inventory[oversized_name]['physical']['st_ino'] and growth['parent_pid'] != terminal['pid']
        assert growth['scope'] == 'BOUNDED_OVERSIZED_REPLACEMENT_NOT_INPLACE_GROWTH'
    if case['id'] == 'G17-source':
        assert bodies[prefix + 'source/backend/capacity_fixture.py'] == base_fixture + b'# SYNTHETIC_PRIVATE_COPY_CHANGED'
    if group == 'G17':
        destination = prefix + 'proof/original-loader-capacity/'
        expected_phases = 3 if variant in ('receipt', 'state', 'source', 'inventory-growth') else 4
        phase_names = sorted(name for name in bodies if name.startswith(destination + 'phase-'))
        assert len(phase_names) == expected_phases
        measurements([bodies[name] for name in phase_names])
        if variant == 'collision':
            assert bodies[destination + 'candidate.json'] == b'ORPHAN_DO_NOT_REPLACE'
        else:
            assert destination + 'candidate.json' not in inventory
    return terminal


# Validate exact frozen source bytes, actual runtimes and every observed child.
def fold(run_root, stage_root, packet_sha, review_root):
    stage_inventory, staged = capture(stage_root)
    packet_raw = staged['packet.json']
    assert sha(packet_raw) == packet_sha
    packet = metadata(packet_raw)
    assert packet['schema'] == 'n2-guard-source-packet/3' and len(packet['files']) == 10
    for name, record in packet['files'].items():
        raw = base64.b64decode(record['base64'], validate=True)
        assert sha(raw) == record['sha256'] and len(raw) == record['bytes']
        assert staged[name] == raw
    review_raw = staged['audit/review.json']
    review = metadata(review_raw)
    assert review['scope'] == 'SOURCE_REVIEWED_SYNTHETIC_ONLY'
    assert review['schema'] == 'n2-guard-source-review/3' and review['guard_manifest_schema'] == MANIFEST_SCHEMA
    assert review['generated_fingerprint'] == FINGERPRINT and review['source_sha256']['harness.py'] == HARNESS_SHA
    for name, checksum in review['source_sha256'].items():
        assert sha(staged['audit/' + name]) == checksum
    inventory, bodies = capture(run_root)
    label = sha((str(run_root) + ':' + sha(review_raw)).encode())
    prepared = metadata(bodies['preparation/prepared/prepared.json'])
    assert prepared['scope'] == 'SYNTHETIC_ONLY_NO_GENUINE_ADMISSION' and prepared['model_or_account_calls'] is False
    assert prepared['schema'] == 'guard-fixtures/3' and prepared['guard_manifest_schema'] == MANIFEST_SCHEMA
    assert prepared['generated_fingerprint'] == FINGERPRINT
    assert len(prepared['files']) == 10
    for name, record in prepared['files'].items():
        raw = bodies['preparation/prepared/source/' + name]
        assert sha(raw) == record['sha256'] and len(raw) == record['bytes']
    before_prepared = metadata(bodies['prepared-before.json'])
    assert before_prepared == metadata(bodies['prepared-after.json']) and len(before_prepared) == 15
    for name, record in before_prepared.items():
        observed = inventory['preparation/prepared/' + name]
        assert record['sha256'] == observed['sha256'] and record['physical'] == observed['physical']
    expected_cases = cases()
    rows_raw = bodies['preparation/prepared/scenarios.json']
    assert sha(rows_raw) == prepared['scenarios_sha256'] and metadata(rows_raw) == expected_cases
    calls_raw = bodies['preparation/prepared/calls.json']
    assert sha(calls_raw) == prepared['calls_sha256']
    calls = metadata(calls_raw)
    assert calls['schema'] == MANIFEST_SCHEMA and set(calls['calls']) == set(PHASES)
    assert calls['fingerprint'] == FINGERPRINT and type(calls['fingerprint']['marshal_version']) is int
    assert len(calls['generated']) == 16
    assert {row['module'] for row in calls['generated']} == {'backend.capacity_dataclass', 'backend.market.replay_broker', 'backend.cli.market_strategy_continue'}
    assert calls['generated'] == prepared['generated']
    bundle_raw = bodies['preparation/prepared/bundle.json']
    bundle = metadata(bundle_raw)
    assert bundle['prepared_sha256'] == sha(bodies['preparation/prepared/prepared.json'])
    assert bundle['source_sha256'] == review['source_sha256'] and bundle['scenarios_sha256'] == sha(rows_raw)
    phase_rows = []
    for role in ('prepare', 'suite'):
        name = 'n2-guard-' + label[:20] + '-' + role
        before, after = (metadata(bodies[role + '-' + edge + '.json']) for edge in ('before', 'after'))
        if role == 'prepare':
            binds = [(str(stage_root / 'audit'), '/audit', False), (str(run_root / 'preparation'), '/out', True)]
            command = ['prepare', '/audit/review.json', sha(review_raw)]
        else:
            binds = [(str(stage_root / 'audit'), '/audit', False), (str(run_root / 'preparation/prepared'), '/fixture', False), (str(run_root / 'preparation/prepared/source'), '/app', False), (str(run_root / 'suite-output'), '/out', True)]
            command = ['suite', '/fixture/bundle.json', sha(bundle_raw)]
        runtime(before, name, label, binds, command, False)
        runtime(after, name, label, binds, command, True)
        assert before['Id'] == after['Id']
        fresh, inspection_sha = inspect_owned(after['Id'], review_root, len(phase_rows))
        # Compare every raw field exactly; mount records bind by unique destination.
        assert set(fresh) == set(after)
        assert {key: value for key, value in fresh.items() if key != 'Mounts'} == {key: value for key, value in after.items() if key != 'Mounts'}
        fresh_mounts = {item['Destination']: item for item in fresh['Mounts']}
        retained_mounts = {item['Destination']: item for item in after['Mounts']}
        assert len(fresh_mounts) == len(fresh['Mounts']) and len(retained_mounts) == len(after['Mounts'])
        assert fresh_mounts == retained_mounts
        observed = [metadata(raw) for key, raw in bodies.items() if key.endswith('.stdout') and raw.lstrip().startswith(b'[') and len(raw) < 262144]
        assert any(type(value) is list and len(value) == 1 and value[0] == after for value in observed)
        phase_rows.append({'role': role, 'cid': after['Id'], 'finished': after['State']['FinishedAt'], 'independent_inspect_sha256': inspection_sha, 'raw_mount_list_order_equal': fresh['Mounts'] == after['Mounts'], 'complete_mount_records_by_unique_destination_equal': True, 'all_other_runtime_fields_exact': True})
    suite_root = run_root / 'suite-output/suite'
    child_inventory, child_bodies = capture(suite_root)
    base_fixture = bodies['preparation/prepared/source/backend/capacity_fixture.py']
    terminals = [child(case, child_inventory, child_bodies, base_fixture) for case in expected_cases]
    suite = metadata(child_bodies['suite.json'])
    assert [item['case'] for item in suite['cases']] == [item['id'] for item in expected_cases]
    assert suite['total_children'] == len(expected_cases) + 4 and suite['genuine_model_or_account_calls'] is False
    assert suite['combined_memory_acceptance'] is False
    assert suite['schema'] == 'n2-guard-synthetic-suite/3' and suite['guard_manifest_schema'] == MANIFEST_SCHEMA
    assert suite['generated_fingerprint'] == FINGERPRINT
    assert len({item['pid'] for item in terminals}) == len(terminals)
    for name in ('timeout', 'interrupt', 'exit7', 'sentinel'):
        prefix = 'G18-' + name + '/'
        terminal = metadata(child_bodies[prefix + 'terminal.json'])
        assert terminal['pid'] not in {item['pid'] for item in terminals}
        assert child_bodies[prefix + 'stderr.log'] == b''
        if name == 'exit7':
            assert terminal['returncode'] == 7 and terminal['owned_stop'] is None
        else:
            assert child_bodies[prefix + 'stdout.log'] == b'READY\n'
            assert terminal['returncode'] in (-15, -9) and terminal['owned_stop'] in ('TERM', 'KILL')
        if name == 'interrupt':
            alarm = metadata(child_bodies[prefix + 'alarm.json'])
            assert alarm['signum'] == 14 and alarm['message'] == 'SYNTHETIC_SUITE_WALL_DEADLINE'
            assert alarm['child_pid'] == terminal['pid'] and 0.05 <= alarm['monotonic'] - alarm['armed'] <= 2
    assert len(suite['cleanup']) == 3 and all(row['sentinel_alive'] is True for row in suite['cleanup'])
    # Detect any later byte/identity changes after the complete independent fold.
    assert capture(stage_root)[0] == stage_inventory and capture(run_root)[0] == inventory
    return {'schema': 'n2-guard-independent-proof/3', 'status': 'SYNTHETIC_ONLY_TERMINAL_ACCEPTANCE',
            'packet_sha256': packet_sha, 'runtimes': phase_rows, 'cases': len(expected_cases),
            'children': len(expected_cases) + 4, 'physical': inventory, 'stage_physical': stage_inventory, 'review_physical': capture(review_root)[0],
            'genuine_source_runtime_admission': False, 'combined_model_memory': False, 'publication': 'CLOSED'}


# Run the independent fold once with a new output root and real finite deadline.
def verify(run_root, stage_root, packet_sha, review_root):
    assert review_root == run_root.parent / (run_root.name + '-independent-review-v3-report-v2')
    assert review_root.parent.resolve(strict=True) == review_root.parent and not review_root.exists()
    review_root.mkdir(mode=0o700)
    prior_handler = signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, 30)
    try:
        return fold(run_root, stage_root, packet_sha, review_root)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prior_handler)


if __name__ == '__main__':
    raise SystemExit('SOURCE_ONLY_REQUIRES_PINNED_CALLER_AND_RUNTIME_ADMISSION')

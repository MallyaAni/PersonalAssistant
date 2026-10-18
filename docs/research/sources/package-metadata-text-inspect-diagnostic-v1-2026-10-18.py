"""Compare only retained inspection evidence after the pre-copy raw-baseline refusal."""
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat

ROOT = Path('/home/animallya96/scratch/capacity-package-metadata-text-census-20261018-v1')
OLD = Path('/home/animallya96/scratch/capacity-package-metadata-head-20261018-v1/inspect-before.stdout')
OUT = Path('/home/animallya96/scratch/capacity-package-metadata-text-inspect-diagnostic-20261018-v1')
TOOLS = Path('/home/animallya96/scratch/capacity-package-metadata-text-tools-20261018-v1/helper.py')
CAP = 262144


# Preserve physical evidence identities using exact decimal strings.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Read one retained bounded regular file twice through a held no-follow descriptor.
def read(path):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
        assert 0 <= before.st_size <= CAP
        raw = os.read(descriptor, CAP + 1)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, CAP + 1) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        return raw, {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}
    finally:
        os.close(descriptor)


# Bound recursive JSON differences without suppressing any unmatched field or list position.
def differences(left, right, path, output):
    assert len(output) < 128
    if type(left) is not type(right):
        output.append({'path': path, 'old': left, 'new': right})
    elif isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                output.append({'path': path + [key], 'old_present': key in left, 'new_present': key in right})
            else:
                differences(left[key], right[key], path + [key], output)
    elif isinstance(left, list):
        if len(left) != len(right):
            output.append({'path': path, 'old_length': len(left), 'new_length': len(right)})
        for index, (a, b) in enumerate(zip(left, right)):
            differences(a, b, path + [index], output)
    elif left != right:
        output.append({'path': path, 'old': left, 'new': right})


# Raise within the read-only helper without issuing any Docker command or cleanup mutation.
def alarm(signum, frame):
    raise TimeoutError('RETAINED_INSPECT_COMPARISON_BOUND')


# Authenticate the failed root and report its complete inspection difference without replaying the reader.
def main():
    assert __debug__ and os.getuid() == 1000
    os.umask(0o077); os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (268435456, 268435456))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    previous = {sig: signal.signal(sig, alarm) for sig in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    signal.alarm(20)
    try:
        names = {'prerequisites.json', 'prior-head-proof.json', 'inspect-before.stdout', 'inspect-before.stderr', 'inspect-before.exit.json'}
        assert {p.name for p in ROOT.iterdir()} == names
        bodies, inventory = {}, {}
        for name in sorted(names):
            bodies[name], inventory[name] = read(ROOT / name)
        old_raw, old_row = read(OLD)
        helper_raw, helper_row = read(TOOLS)
        assert old_row['sha256'] == 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'
        assert helper_row['sha256'] == 'a9af8e55fb60b2b950aeada945b7e0ac354fe853a3efeeb6ba4809ba8c226a60'
        assert inventory['prior-head-proof.json']['sha256'] == '4a30076a7e6b530b7e24ffa1990abeb6d7a817974d96ef3d6f8100b1e7e111ab'
        terminal = json.loads(bodies['inspect-before.exit.json'])
        assert terminal['arguments'] == ['docker', '--host', 'unix:///var/run/docker.sock', 'container', 'inspect',
            '803718a62e3cbd1f6070abab25a58e1fbc0ee5d04b5444f57c817d7e47b8bf57']
        assert terminal['exit'] == 0 and terminal['owned_CLI_group_stop'] is None
        assert terminal['failure_class'] is None and terminal['cleanup_failure_class'] is None
        assert terminal['overflow_first_extra_byte_hex'] == {} and bodies['inspect-before.stderr'] == b''
        for channel in ('stdout', 'stderr'):
            name = 'inspect-before.' + channel
            assert terminal['outputs'][channel] == {'file': name, 'bytes': inventory[name]['bytes'], 'sha256': inventory[name]['sha256']}
        old, new = json.loads(old_raw), json.loads(bodies['inspect-before.stdout'])
        assert len(old) == len(new) == 1
        delta = []
        differences(old, new, [], delta)
        old_mounts, new_mounts = old[0]['Mounts'], new[0]['Mounts']
        assert all(isinstance(m, dict) and isinstance(m['Destination'], str) for m in old_mounts + new_mounts)
        assert len({m['Destination'] for m in old_mounts}) == len(old_mounts)
        assert len({m['Destination'] for m in new_mounts}) == len(new_mounts)
        non_mounts_equal = {k: v for k, v in old[0].items() if k != 'Mounts'} == {k: v for k, v in new[0].items() if k != 'Mounts'}
        complete_mounts_equal = {m['Destination']: m for m in old_mounts} == {m['Destination']: m for m in new_mounts}
        for name in sorted(names):
            assert read(ROOT / name) == (bodies[name], inventory[name])
        assert read(OLD) == (old_raw, old_row) and read(TOOLS) == (helper_raw, helper_row)
        proof = {'schema': 'retained-metadata-text-inspect-diagnostic/1',
            'status': 'READONLY_COMPARISON_ONLY_ORIGINAL_COPY_ATTEMPT_FAILED_NOT_REPLAYED',
            'failed_root_inventory': inventory, 'old_inspect': old_row, 'failed_helper': helper_row,
            'all_JSON_differences': delta, 'decoded_equal': old == new,
            'all_nonMounts_fields_equal': non_mounts_equal,
            'complete_uniqueDestination_mount_records_equal': complete_mounts_equal,
            'raw_Mounts_list_order_equal': old_mounts == new_mounts,
            'new_inspect_sha256': inventory['inspect-before.stdout']['sha256'],
            'content_copy_terminals_in_failed_root': 0,
            'Docker_HEAD_cp_probe_or_package_body_execution': False}
        raw = json.dumps(proof, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
        assert len(raw) <= CAP and OUT.parent.resolve(strict=True) == OUT.parent
        OUT.mkdir(mode=0o700, exist_ok=False)
        with (OUT / 'proof.json').open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        assert read(OUT / 'proof.json')[0] == raw
        descriptor = os.open(OUT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.fsync(descriptor); os.close(descriptor)
        print(raw.decode(), end='')
    finally:
        signal.alarm(0)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()

"""UNRUN transport source fragment; supplied constants exist only in the generated proposed transport."""


# Authenticate a bounded local packet or actual prerequisite with two held/named reads.
def local_read(path, pin, record=True):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1 and 0 <= before.st_size <= 65536
        raw = os.read(fd, 65537)
        os.lseek(fd, 0, os.SEEK_SET)
        assert os.read(fd, 65537) == raw and len(raw) == before.st_size
        physical = {key: str(getattr(before, key)) for key in FIELDS}
        assert physical == {key: str(getattr(os.fstat(fd), key)) for key in FIELDS} == {key: str(getattr(os.lstat(path), key)) for key in FIELDS}
        row = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'physical': physical}
        assert all(row[key] == value for key, value in pin.items())
        if record:
            LOCAL_INPUTS[str(path)] = row
        return raw, row
    finally:
        os.close(fd)


# Build only a bounded wire from the frozen packet and an externally pinned actual prerequisite.
def prepare():
    assert hashlib.sha256(BOOTSTRAP.encode('utf-8')).hexdigest() == BOOTSTRAP_SHA
    raw, _ = local_read(PREPARATION / 'packet.json', {'bytes': PACKET_BYTES, 'sha256': PACKET_SHA})
    prior = None
    if sys.argv[1] in ('stage', 'observe'):
        expected = sys.argv[2]
        assert len(expected) == 64 and set(expected) <= set('0123456789abcdef')
        phase = 'before-stage' if sys.argv[1] == 'stage' else 'before-observe'
        path = Path('/tmp/native-origin-' + phase + '-transport-20261018-v1/stdout')
        prior, _ = local_read(path, {'sha256': expected})
        proof = json.loads(prior)
        assert proof['schema'] == 'native-origin-readonly-prerequisite/1' and proof['phase'] == phase
        assert proof['control_source_sha256'] == BOOTSTRAP_SHA and proof['base_packet_sha256'] == PACKET_SHA
        assert proof['source_pins'] == SOURCE_ROWS and proof['hostname'] == 'animallya-spark1' and type(proof['uid']) is int and proof['uid'] == 1000
        assert proof['reader_executed'] is False and proof['native_runtime_admission'] is None
        observed = proof['observed_at_ns']
        assert type(observed) is str and observed.isascii() and observed.isdecimal() and str(int(observed)) == observed
        assert 0 <= time.time_ns() - int(observed) <= 300000000000
    wire = json.dumps({'base_packet_base64': base64.b64encode(raw).decode('ascii'),
        'prerequisite_base64': None if prior is None else base64.b64encode(prior).decode('ascii')},
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii') + b'\n'
    assert len(wire) <= 65536
    return wire

"""One fresh context73 native metadata observation; no backend/model/account/data mount."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path


# Observe the actual image-native NumPy origin and thread settings without importing an application.
def main(arguments):
    assert arguments == ['diagnose'] and os.getuid() == 1000 and list(Path('/out').iterdir()) == []
    keys = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS')
    for key in keys:
        os.environ[key] = '1'
    native = Path('/usr/local/lib/python3.12/site-packages')
    assert native.resolve(strict=True) == native
    sys.path.append(str(native))
    import numpy
    origin = Path(numpy.__file__).resolve(strict=True)
    assert origin == native / 'numpy/__init__.py' and numpy.__version__ == '2.5.3' and sys.version.split()[0] == '3.12.14'
    backend = [name for name in sys.modules if name == 'backend' or name.startswith('backend.')]
    assert backend == []
    result = {'schema': 'capacity-context-native-probe/1', 'uid': os.getuid(), 'observed_at_ns': str(time.time_ns()),
        'python': sys.version.split()[0], 'python_executable': sys.executable,
        'numpy': {'version': numpy.__version__, 'path': str(origin), 'init_sha256': hashlib.sha256(origin.read_bytes()).hexdigest()},
        'threads': {key: os.environ[key] for key in keys}, 'backend_modules': backend, 'parity_or_genuine_acceptance': False}
    raw = json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= 262144
    with Path('/out/native.json').open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert Path('/out/native.json').read_bytes() == raw


if __name__ == '__main__':
    main(sys.argv[1:])

"""One scoped NumPy import metadata probe; no app/module/model/data mounts."""
import hashlib
import json
import os
import sys
from pathlib import Path

# Record actual image-native Python/NumPy identity without importing an application.
def main(arguments):
    assert arguments==['diagnose'] and os.getuid()==1000 and list(Path('/out').iterdir())==[]
    keys=('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS')
    for name in keys:os.environ[name]='1'
    native=Path('/usr/local/lib/python3.12/site-packages');assert native.resolve(strict=True)==native
    sys.path.append(str(native))
    import numpy
    origin=Path(numpy.__file__).resolve(strict=True);assert origin==native/'numpy/__init__.py'
    backend=[name for name in sys.modules if name=='backend' or name.startswith('backend.')];assert backend==[]
    value={'scope':'NUMPY_IMPORT_METADATA_ONLY_NO_MODEL_OR_APP','uid':os.getuid(),'python':sys.version.split()[0],'python_executable':sys.executable,'numpy_version':str(numpy.__version__),'numpy_file':str(origin),'numpy_init_sha256':hashlib.sha256(origin.read_bytes()).hexdigest(),'backend_modules':backend,'thread_limits':{name:os.environ[name] for name in keys}}
    raw=json.dumps(value,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n';assert len(raw)<=262144
    path=Path('/out/native.json')
    with path.open('xb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
    assert path.read_bytes()==raw

if __name__=='__main__':main(sys.argv[1:])

"""Private writable application caches, then the unchanged-device experiment entry."""
import os
from pathlib import Path
import runpy

for key in ('XDG_CACHE_HOME', 'TORCH_HOME', 'TRITON_CACHE_DIR',
            'MIOPEN_USER_DB_PATH', 'MIOPEN_CUSTOM_CACHE_DIR'):
    directory = Path(os.environ[key])
    if not directory.is_relative_to('/tmp/qa-cache'):
        raise ValueError('Application cache must remain in private container tmpfs')
    directory.mkdir(parents=True, exist_ok=True)
runpy.run_path('/qa-bundle/vision_daemon.py', run_name='__main__')

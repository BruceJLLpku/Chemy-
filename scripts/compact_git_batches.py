"""Compact existing Git packs in bounded batches without pruning history."""
import shutil
from publish_library import git,ROOT
before=git('rev-parse','HEAD')
git('-c','pack.windowMemory=192m','-c','pack.threads=2','multi-pack-index','write')
git('-c','pack.windowMemory=192m','-c','pack.threads=2','multi-pack-index','repack','--batch-size=1073741824')
git('multi-pack-index','expire')
assert git('rev-parse','HEAD')==before
print('GIT BATCH preserved HEAD',before,'free bytes',shutil.disk_usage(ROOT).free,flush=True)

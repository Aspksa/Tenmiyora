"""Prepare a tiny, valid release manifest for the disposable Windows smoke."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from release_staging import snapshot

def prepare(target):
    base=Path(target)
    source=base/"candidate"
    (source/"web").mkdir(parents=True)
    (source/"web"/"release-smoke.txt").write_text("release-smoke\n",encoding="utf-8")
    snapshot(source,base/"package")

if __name__=="__main__":
    prepare(sys.argv[1])

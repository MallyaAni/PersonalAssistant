"""Release-only installation of explicitly reviewed original simulation data."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from backend.market import strategy_history_installation as installation


# Read only the committed bounded review from the exact gated revision before admitting its finite assets.
def reviewed(root,path,digest,revision):
    code=Path(__file__).resolve().parents[2];relative=Path(path)
    if (relative.is_absolute() or '..' in relative.parts or relative.parts[:2]!=('docs','research')
            or subprocess.check_output(['git','-C',str(code),'rev-parse','HEAD'],text=True).strip()!=revision):
        raise ValueError('Exact committed historical release review required')
    selected=code/relative
    raw=installation.history._read(selected,131072)
    if (sha256(raw).hexdigest()!=digest or raw!=subprocess.check_output(['git','-C',str(code),'show',revision+':'+relative.as_posix()])):
        raise ValueError('Historical release review is not the committed original')
    review=json.loads(raw);source=Path(review['source_directory'])
    if (source.is_absolute() or '..' in source.parts or source.parts[:3]!=('backend','market','data')
            or not (code/source).resolve().is_relative_to(code)):
        raise ValueError('Committed finite historical asset directory required')
    config=json.loads((Path(root)/installation.history.learned_live_holding.CONFIG).read_bytes())
    return installation.prepare(code/source,review,config['cost_bps'])


# Expose explicit preflight, installation and exact-selector rollback to the canonical deploy workflow.
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('preflight','install','rollback'))
    parser.add_argument('--root',required=True)
    parser.add_argument('--review');parser.add_argument('--review-sha256');parser.add_argument('--revision')
    parser.add_argument('--archive-dir');parser.add_argument('--archive')
    args=parser.parse_args()
    if args.action=='rollback':
        if not args.archive:parser.error('rollback requires --archive')
        result=installation.rollback(args.root,args.archive)
    else:
        if not all((args.review,args.review_sha256,args.revision)):
            parser.error('explicit committed review, digest and revision required')
        prepared=reviewed(args.root,args.review,args.review_sha256,args.revision)
        if args.action=='preflight':
            result={'status':'ORIGINAL_HISTORY_ASSETS_ADMITTED','history_sha256':prepared['review']['history_sha256'],
                'stocks':len(prepared['files']),'recommendations':prepared['review']['recommendations']}
        else:
            if not args.archive_dir:parser.error('installation requires --archive-dir')
            result=installation.install(args.root,prepared,args.archive_dir)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()

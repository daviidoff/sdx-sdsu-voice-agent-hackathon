"""Merge independent shards, preserving provenance and screenshot links."""
import argparse
import json
from pathlib import Path
import shutil
from evaluation.report import write_report


def merge(inputs, output):
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=True)
    result={'metadata':{'shards':[],'limitations':['Merged runs; inspect per-shard configuration for drift. Semantic review remains required.']},'cases':[]}
    seen=set()
    for index,folder in enumerate(inputs):
        folder=Path(folder).resolve()
        data=json.loads((folder/'results.json').read_text())
        result['metadata']['shards'].append(data['metadata'])
        for original in data['cases']:
            case=json.loads(json.dumps(original))
            identity=(case['key'],case.get('repetition',1))
            if identity in seen:
                raise ValueError('Duplicate case/repetition: '+str(identity))
            seen.add(identity)
            for step in case.get('steps',[]):
                if step.get('screenshot'):
                    source=(folder/step['screenshot']).resolve()
                    if not source.is_relative_to(folder):
                        raise ValueError('Screenshot path escapes input directory')
                    target=output/f'shard-{index}'/step['screenshot']
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(source,target)
                    step['screenshot']=str(target.relative_to(output))
            result['cases'].append(case)
    result['cases'].sort(key=lambda c:(c['key'],c.get('repetition',1)))
    write_report(output,result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('inputs',nargs='+')
    p.add_argument('--output',required=True)
    a=p.parse_args()
    result=merge(a.inputs,a.output)
    print(json.dumps(result['counts']))
    print(str(Path(a.output).resolve()/'report.html'))


if __name__=='__main__':
    main()

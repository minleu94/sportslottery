from pathlib import Path
import sys,json,zipfile,hashlib,subprocess,ast
root=Path(__file__).resolve().parents[2];out=root/'artifacts/optimization_20261014';installed=out/'installed_release';workspace=out/'portable_workspace_release'
sys.path.insert(0,str(installed))
from sportslottery_bootstrap import materialize_workspace
materialize_workspace(workspace)
proc=subprocess.run([sys.executable,str(workspace/'main.py'),'research-pipeline','--dry-run'],cwd=workspace,capture_output=True,text=True,encoding='utf-8')
(out/'portable_dry_run.json').write_text(proc.stdout,encoding='utf-8')
wheel=out/'dist/sportslottery-2.0.1-py3-none-any.whl'
with zipfile.ZipFile(wheel) as z:
 names=z.namelist();checked={name:hashlib.sha256(z.read(name)).hexdigest()==hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names if (root/name).is_file() and name.endswith(('.py','.yaml','.yml','.ps1','.bat'))}
 required=['app.py','main.py','core/research_mlb.py','config/research_pipeline.yaml','scripts/install_research_task.ps1']+[p.relative_to(root).as_posix() for p in (root/'pages').glob('*.py')]
receipt={'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'version':'2.0.1','independent_install_root':str(installed),'workspace':str(workspace),'dry_run_exit_code':proc.returncode,'dry_run_stderr':proc.stderr,'packaged_source_files':len(checked),'all_packaged_sources_match':all(checked.values()),'required_resources':{name:name in names for name in required},'installed_files_match':all(hashlib.sha256((installed/name).read_bytes()).hexdigest()==hashlib.sha256((root/name).read_bytes()).hexdigest() for name in checked)}
(out/'deployment_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
files=[p for d in ['core','integrations','probability','ui','scripts','pages','config'] for p in (root/d).rglob('*.py') if '__pycache__' not in p.parts]+[root/f for f in ['app.py','main.py','launcher.py','sportslottery_bootstrap.py']]
for p in files:ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p))
(out/'syntax_receipt.json').write_text(json.dumps({'method':'AST parse only; no tests added or run','file_count':len(files),'status':'COMPLETE','sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}},indent=2),encoding='utf-8')
print(json.dumps(receipt,ensure_ascii=True,indent=2))

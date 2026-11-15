"""Reproduce the two streaming resource controls without modifying a checkout."""
from pathlib import Path
import io
import subprocess
import sys
import tarfile
import tempfile

checkout = Path(sys.argv[1]).absolute()
methods = (
    'test_discovery_releases_prior_root_results_as_it_scans_duplicate_roots',
    'test_repeated_bindings_and_exits_construct_only_emitted_findings',
)
for revision, expected in [('933a1bc', 1), ('a5b7ca4', 0)]:
    with tempfile.TemporaryDirectory(prefix='messpy-resource-control-') as temporary:
        root = Path(temporary)
        archive = subprocess.check_output(['git', 'archive', revision, 'src/messpy'], cwd=checkout)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(root, filter='data')
        (root / 'tests').mkdir()
        (root / 'tests/test_state_analyzer.py').write_bytes((checkout / 'tests/test_state_analyzer.py').read_bytes())
        for method in methods:
            command = [sys.executable, '-m', 'unittest', 'discover', '-s', str(root / 'tests'), '-p', 'test_state_analyzer.py', '-k', method]
            result = subprocess.run(command, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            print(f'{revision}: {method}: exit {result.returncode}; expected {expected}', flush=True)
            print(result.stdout, flush=True)
            assert result.returncode == expected, 'Unexpected resource control result'
            if expected:
                assert 'AssertionError' in result.stdout and 'FAILED (failures=' in result.stdout
                assert 'Ran 1 test' in result.stdout
print('Both resource controls reject the buffered source and pass the final production source.')

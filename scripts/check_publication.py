"""Heuristic pre-publication scan. Prints paths/rules only, never matched values.

Checks tracked index content and tracked/unignored working files. Not a historical
secret audit; intentionally does not read ignored credentials or collected PDFs.
"""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'provider credential': re.compile(rb'(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})'),
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'literal secret assignment': re.compile(rb'''(?im)^[ \t]*(?:export[ \t]+)?(?:LAS_API_KEY|OPENAI_KEY|OPENAI_API_KEY|AWS_SECRET_ACCESS_KEY)[ \t]*=[ \t]*["']?([^\s"'\#]+)'''),
    'credential-bearing URL': re.compile(rb'https?://[^/\s:@]+:[^/\s@]+@'),
}


def safe_placeholder(value):
    return (value in (b'=', b'None', b'null') or value.startswith((b'<', b'${', b'os.', b'process.', b'test-', b'fake-', b'example-', b'fixture-')))


def findings(path, raw):
    issues = set()
    p = Path(path)
    if p.name.startswith('.env') and p.name != '.env.example': issues.add('environment file')
    if (any(part in ('node_modules', '.venv', 'var', 'data', 'exports', 'backups') for part in p.parts)
            or p.suffix.lower() in ('.pdf', '.sqlite', '.sqlite3', '.db', '.pem', '.key', '.log', '.xlsx', '.zip', '.tgz')
            or p.name.endswith(('-wal', '-shm', '.tar.gz'))):
        issues.add('runtime/secret/document artifact')
    for rule, pattern in PATTERNS.items():
        # These tests deliberately supply invalid credential URLs to exercise rejection.
        # Provider-key/private-key/literal-secret checks still apply to every test file.
        if rule == 'credential-bearing URL' and path in {
            'backend/tests/test_collection.py',
            'backend/tests/test_pipeline.py',
            'backend/tests/test_las.py',
            'backend/tests/test_intake.py',
        }: continue
        for match in pattern.finditer(raw):
            if rule == 'literal secret assignment' and safe_placeholder(match[1]): continue
            issues.add(rule)
    return sorted(issues)


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def main():
    paths = set(git('ls-files', '-z', '--cached', '--others', '--exclude-standard').decode().split('\0')) - {''}
    tracked = set(git('ls-files', '-z', '--cached').decode().split('\0')) - {''}
    failures = []
    for path in sorted(paths):
        file = ROOT / path
        if file.is_file():
            failures.extend((path, 'working tree', rule) for rule in findings(path, file.read_bytes()))
        if path in tracked:
            raw = git('show', ':./' + path)
            failures.extend((path, 'index', rule) for rule in findings(path, raw))
    for path, location, rule in failures:
        print(f'CHECK: {path} ({location}): {rule}')
    print(f'Publication scan: {len(paths)} working paths, {len(tracked)} indexed paths; {len(failures)} findings. Values redacted.')
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())

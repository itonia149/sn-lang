#!/usr/bin/env python3
from pathlib import Path
import subprocess, tempfile, sys
ROOT = Path(__file__).resolve().parents[1]


def run(*cmd, input=None):
    return subprocess.run(cmd, cwd=ROOT, input=input, text=True, capture_output=True, check=True)


def main():
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        # Normal v1 compile + runtime.
        ll=td/'functions.ll'; exe=td/'functions'
        r=run(sys.executable, 'snc.py', 'examples/functions.sn', '-o', str(ll))
        assert "asymmetric function 'difference'" in r.stderr
        run('clang', str(ll), 'runtime.c', '-o', str(exe))
        assert run(str(exe)).stdout == '42\n42\n'

        # Stage-1 compiler written in Sn, using only sfuncs.
        bootll=td/'snc_core.ll'; boot=td/'snc_core'
        r=run(sys.executable, 'snc.py', 'bootstrap/snc_core.sn', '-o', str(bootll), '--deny-warnings')
        assert r.stderr == ''
        run('clang', str(bootll), 'runtime.c', '-o', str(boot))
        corell=td/'core.ll'; core=td/'core'
        run(str(boot), 'bootstrap/example_core.sn', str(corell))
        run('clang', str(corell), '-o', str(core))
        assert run(str(core)).stdout == '42\n'

        # Adventure game: scripted playthrough.
        gamell=td/'game.ll'; game=td/'game'
        r=run(sys.executable, 'snc.py', 'examples/adventure.sn', '-o', str(gamell))
        assert "asymmetric function" in r.stderr
        run('clang', str(gamell), 'runtime.c', '-o', str(game))
        script='look\nnorth\nkey\nsouth\nquit\n'
        out=run(str(game), input=script).stdout
        assert 'SN ADVENTURE' in out and 'brass key' in out and 'Fin.' in out
    print('all end-to-end tests passed')

if __name__ == '__main__': main()

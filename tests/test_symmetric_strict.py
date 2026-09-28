#!/usr/bin/env python3
from pathlib import Path
import itertools, subprocess, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from snc import compile_source, CompileError, parse_program, resolve_program, asymmetric_uses


def run(*cmd, input=None):
    return subprocess.run(cmd,cwd=ROOT,input=input,text=True,capture_output=True,check=True)


def main():
    # print/arg/choose/par and the arithmetic/Boolean core are symmetric intrinsics.
    src='''
    sfunc pick(x:i64)->str = { choose { when { eq x 1 } "one" } { when { eq x 2 } "two" } };
    main = { print { pick 1 } };
    '''
    p,ir=compile_source(src,symmetric_only=True)
    assert asymmetric_uses(p)==[]

    # The old string-building bootstrap is now correctly exposed as impure.
    old=(ROOT/'bootstrap/snc_core.sn').read_text()
    try:
        compile_source(old,symmetric_only=True)
    except CompileError as e:
        assert "asymmetric primitive 'concat'" in str(e)
    else:
        raise AssertionError('old bootstrap unexpectedly passed strict audit')

    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        # All-sfunc adventure.
        ll=td/'game.ll'; exe=td/'game'
        run(sys.executable,'snc.py','examples/adventure_sfunc.sn','-o',str(ll),'--symmetric-only','--deny-warnings')
        run('clang',str(ll),'runtime.c','-o',str(exe))
        events=['1:north','2:key','3:south','4:unlock']
        outs=set()
        for q in itertools.permutations(events):
            outs.add(run(str(exe),*q).stdout)
        assert outs=={'You unlock the cellar door and escape. You win.\n'}

        # Strict symmetric compiler kernel + trusted LLVM serializer.
        kll=td/'kernel.ll'; kexe=td/'kernel'
        run(sys.executable,'snc.py','bootstrap/symmetric_kernel.sn','-o',str(kll),'--symmetric-only','--deny-warnings')
        run('clang',str(kll),'runtime.c','-o',str(kexe))
        llvm=set()
        for q in itertools.permutations(['print','add','20','22']):
            facts=run(str(kexe),*q).stdout
            llvm.add(run(sys.executable,'bootstrap/ir_serializer.py',input=facts).stdout)
        assert len(llvm)==1
        outll=td/'out.ll'; out=td/'out'
        outll.write_text(next(iter(llvm)))
        run('clang',str(outll),'-o',str(out))
        assert run(str(out)).stdout=='42\n'
    print('all strict symmetric tests passed')

if __name__=='__main__': main()

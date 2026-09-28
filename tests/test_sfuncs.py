#!/usr/bin/env python3
from pathlib import Path
import itertools, subprocess, sys, tempfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from snc import compile_source, CompileError


def must_fail(src, needle):
    try:
        compile_source(src)
    except CompileError as e:
        assert needle in str(e), (needle, str(e))
    else:
        raise AssertionError("expected failure")


def test_sfunc_accepts():
    src='''
    sfunc plus(a:i64,b:i64)->i64 = { add a b };
    main = { print { plus 2 3 } };
    '''
    p, ir = compile_source(src)
    assert not p.warnings
    assert '@sn_plus' in ir


def test_sfunc_rejects_asymmetry():
    src='''
    sfunc minus(a:i64,b:i64)->i64 = { sub a b };
    main = { print 0 };
    '''
    must_fail(src, "not permutation-invariant")


def test_afunc_warns():
    src='''
    afunc minus(a:i64,b:i64)->i64 = { sub a b };
    main = { print { minus 9 4 } };
    '''
    p, _ = compile_source(src)
    assert p.warnings == ["warning: call to asymmetric function 'minus'"]


def test_sfunc_call_permutations_same_ir():
    base='''sfunc plus(a:i64,b:i64)->i64 = { add a b };\nmain = { print { %s } };\n'''
    irs=[]
    for q in itertools.permutations(["plus","2","3"]):
        _, ir=compile_source(base % " ".join(q)); irs.append(ir)
    assert len(set(irs))==1


def test_afunc_order_changes_ir():
    a='''afunc minus(a:i64,b:i64)->i64 = { sub a b }; main = { print { minus 9 4 } };'''
    b='''afunc minus(a:i64,b:i64)->i64 = { sub a b }; main = { print { minus 4 9 } };'''
    _, ia=compile_source(a); _, ib=compile_source(b)
    assert ia != ib


if __name__ == '__main__':
    test_sfunc_accepts(); test_sfunc_rejects_asymmetry(); test_afunc_warns(); test_sfunc_call_permutations_same_ir(); test_afunc_order_changes_ir()
    print('all sfunc/afunc tests passed')

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast as pyast
from dataclasses import dataclass, field
import hashlib
import itertools
import re
import sys
from pathlib import Path
from typing import Iterable, Union

# Sn v1: unordered call syntax + checked symmetric user functions.
#
#   sfunc sum(a:i64, b:i64) -> i64 = { sum a b };   # recursive example, if desired
#   sfunc plus(a:i64, b:i64) -> i64 = { add a b };
#   afunc minus(a:i64, b:i64) -> i64 = { sub a b };
#   main = { print { plus 2 3 } };
#
# In a brace call, the operator token may occur anywhere. For sfuncs and symmetric
# builtins the operands are semantically a multiset and are canonicalized. For
# afuncs and asymmetric builtins, the operator may move but the relative order of
# the remaining operands is preserved.


class CompileError(Exception):
    pass


@dataclass(frozen=True)
class Token:
    text: str
    pos: int


@dataclass(frozen=True)
class Atom:
    kind: str  # int | bool | string | symbol
    value: object
    pos: int = -1


@dataclass(frozen=True)
class RawSet:
    items: tuple["Raw", ...]
    pos: int = -1


Raw = Union[Atom, RawSet]


@dataclass(frozen=True)
class Expr:
    op: str | None
    args: tuple["Expr", ...] = ()
    kind: str | None = None
    value: object | None = None
    ty: str = ""
    symmetry: str = "s"  # s|a|atom; used by canonical rendering

    def canonical(self) -> str:
        if self.op is None:
            if self.kind == "string":
                return repr(self.value)
            if self.kind == "bool":
                return "true" if self.value else "false"
            return str(self.value)
        return "{" + " ".join([self.op, *(a.canonical() for a in self.args)]) + "}"


@dataclass
class FunctionDef:
    kind: str  # sfunc | afunc
    name: str
    params: list[tuple[str, str]]
    ret: str
    body_raw: Raw
    body: Expr | None = None


@dataclass
class Program:
    funcs: dict[str, FunctionDef] = field(default_factory=dict)
    main_raw: Raw | None = None
    main: Expr | None = None
    warnings: list[str] = field(default_factory=list)


SCALAR_TYPES = {"i64", "i1", "str", "unit"}

# Symmetric primitives. Their operands have no positional meaning.
SYM_BUILTINS = {
    "add": ("i64", "i64"),
    "mul": ("i64", "i64"),
    "and": ("i1", "i1"),
    "or": ("i1", "i1"),
    "xor": ("i1", "i1"),
    "nand": ("i1", "i1"),
    "eq": ("poly", "i1"),
    # Unary/nullary primitives are genuinely permutation-invariant: there is
    # no argument order to observe. They are part of the symmetric prelude.
    "strlen": ("str", "i64"),
    "trim": ("str", "str"),
    "wordcount": ("str", "i64"),
    "firstline": ("str", "str"),
    "restlines": ("str", "str"),
    "readfile": ("str", "str"),
    "arg": ("i64", "str"),
    "argc": ("nullary", "i64"),
    "readline": ("nullary", "str"),
    "print": ("poly1", "unit"),
    "itoa": ("i64", "str"),
    "atoi": ("str", "i64"),
    "b2i": ("i1", "i64"),
    # Symmetric guarded choice. `when` consumes an unordered {i1, value}
    # pair; `choose` consumes an unordered multiset of choices and requires
    # exactly one guard to be true at runtime.
    "when": ("choice", "choice"),
    "choose": ("choice", "poly"),
    "par": ("unit", "unit"),
}

# Primitives whose semantics genuinely depends on operand roles/order.  They
# remain available to ordinary Sn programs, but --symmetric-only rejects them.
ASYM_BUILTINS = {
    "sub", "div", "mod", "lt", "le", "concat", "if", "seq",
    "startswith", "contains", "slice", "charat", "replace", "word",
    "writefile",
}
ALL_BUILTINS = set(SYM_BUILTINS) | ASYM_BUILTINS


LEX_RE = re.compile(
    r'''\s*(?:(?P<comment>\#.*)|(?P<arrow>->)|(?P<string>"(?:\\.|[^"\\])*")|(?P<punct>[{}(),:;=])|(?P<atom>[^\s{}(),:;=]+))'''
)


def lex(src: str) -> list[Token]:
    out: list[Token] = []
    pos = 0
    while pos < len(src):
        m = LEX_RE.match(src, pos)
        if not m:
            if src[pos:].strip() == "":
                break
            raise CompileError(f"cannot tokenize near byte {pos}: {src[pos:pos+30]!r}")
        pos = m.end()
        if m.group("comment") is not None:
            continue
        text = m.group("arrow") or m.group("string") or m.group("punct") or m.group("atom")
        if text is not None:
            out.append(Token(text, m.start()))
    return out


class Parser:
    def __init__(self, src: str):
        self.toks = lex(src)
        self.i = 0

    def peek(self, text: str | None = None) -> bool:
        if self.i >= len(self.toks):
            return False
        return text is None or self.toks[self.i].text == text

    def take(self, text: str | None = None) -> Token:
        if self.i >= len(self.toks):
            raise CompileError("unexpected end of input")
        t = self.toks[self.i]
        if text is not None and t.text != text:
            raise CompileError(f"expected {text!r} near byte {t.pos}, got {t.text!r}")
        self.i += 1
        return t

    def atom_from(self, t: Token) -> Atom:
        tok = t.text
        if tok.startswith('"'):
            try:
                v = pyast.literal_eval(tok)
            except Exception as e:
                raise CompileError(f"invalid string literal at byte {t.pos}: {e}") from e
            return Atom("string", v, t.pos)
        if tok == "true":
            return Atom("bool", True, t.pos)
        if tok == "false":
            return Atom("bool", False, t.pos)
        if re.fullmatch(r"-?\d+", tok):
            return Atom("int", int(tok), t.pos)
        return Atom("symbol", tok, t.pos)

    def raw_expr(self) -> Raw:
        if self.peek("{"):
            start = self.take("{").pos
            items: list[Raw] = []
            while not self.peek("}"):
                if not self.peek():
                    raise CompileError("missing '}'")
                items.append(self.raw_expr())
            self.take("}")
            if not items:
                raise CompileError("empty unordered expression")
            return RawSet(tuple(items), start)
        t = self.take()
        if t.text in {"}", ")", ",", ":", ";", "=", "->"}:
            raise CompileError(f"unexpected token {t.text!r} near byte {t.pos}")
        return self.atom_from(t)

    def parse_program(self) -> Program:
        p = Program()
        while self.peek():
            kind = self.take().text
            if kind in {"sfunc", "afunc"}:
                name = self.take().text
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                    raise CompileError(f"invalid function name {name!r}")
                if name in p.funcs or name in ALL_BUILTINS:
                    raise CompileError(f"duplicate/reserved function name {name!r}")
                self.take("(")
                params: list[tuple[str, str]] = []
                if not self.peek(")"):
                    while True:
                        pn = self.take().text
                        self.take(":")
                        pt = self.take().text
                        if pt not in SCALAR_TYPES - {"unit"}:
                            raise CompileError(f"unsupported parameter type {pt!r}")
                        params.append((pn, pt))
                        if self.peek(","):
                            self.take(",")
                            continue
                        break
                self.take(")")
                self.take("->")
                ret = self.take().text
                if ret not in SCALAR_TYPES:
                    raise CompileError(f"unsupported return type {ret!r}")
                self.take("=")
                body = self.raw_expr()
                self.take(";")
                if len({n for n, _ in params}) != len(params):
                    raise CompileError(f"duplicate parameter in {name}")
                p.funcs[name] = FunctionDef(kind, name, params, ret, body)
            elif kind == "main":
                if p.main_raw is not None:
                    raise CompileError("duplicate main")
                self.take("=")
                p.main_raw = self.raw_expr()
                self.take(";")
            else:
                raise CompileError(f"expected sfunc, afunc, or main; got {kind!r}")
        if p.main_raw is None:
            raise CompileError("program has no main")
        return p


def parse_program(src: str) -> Program:
    return Parser(src).parse_program()


@dataclass
class ResolveContext:
    program: Program
    locals: dict[str, str]
    current_func: str | None


def _sym_builtin_type(op: str, args: list[Expr]) -> str:
    if op in {"add", "mul"}:
        if len(args) < 2 or any(a.ty != "i64" for a in args):
            raise CompileError(f"{op} expects at least two i64 operands")
        return "i64"
    if op in {"and", "or", "xor"}:
        if len(args) < 2 or any(a.ty != "i1" for a in args):
            raise CompileError(f"{op} expects at least two i1 operands")
        return "i1"
    if op == "nand":
        if len(args) != 2 or any(a.ty != "i1" for a in args):
            raise CompileError("nand expects exactly two i1 operands")
        return "i1"
    if op == "eq":
        if len(args) != 2 or args[0].ty != args[1].ty or args[0].ty not in {"i64", "i1", "str"}:
            raise CompileError("eq expects two operands of the same scalar type")
        return "i1"
    unary = {
        "strlen": ("str", "i64"), "trim": ("str", "str"),
        "wordcount": ("str", "i64"), "firstline": ("str", "str"),
        "restlines": ("str", "str"), "readfile": ("str", "str"),
        "arg": ("i64", "str"), "itoa": ("i64", "str"),
        "atoi": ("str", "i64"), "b2i": ("i1", "i64"),
    }
    if op in unary:
        at, ret = unary[op]
        if len(args) != 1 or args[0].ty != at:
            raise CompileError(f"{op} expects one {at} operand")
        return ret
    if op in {"argc", "readline"}:
        if args:
            raise CompileError(f"{op} expects no operands")
        return "i64" if op == "argc" else "str"
    if op == "print":
        if len(args) != 1 or args[0].ty not in {"i64", "i1", "str"}:
            raise CompileError("print expects one scalar operand")
        return "unit"
    if op == "when":
        if len(args) != 2:
            raise CompileError("when expects an unordered guard/value pair")
        conds = [a for a in args if a.ty == "i1"]
        vals = [a for a in args if a.ty in {"i64", "str"}]
        if len(conds) != 1 or len(vals) != 1:
            raise CompileError("when expects exactly one i1 guard and one i64/str value")
        return "choice_" + vals[0].ty
    if op == "choose":
        if len(args) < 1 or any(not a.ty.startswith("choice_") for a in args):
            raise CompileError("choose expects one or more guarded choices")
        tys = {a.ty for a in args}
        if len(tys) != 1:
            raise CompileError("all choose alternatives must have the same value type")
        return next(iter(tys))[len("choice_"):]
    if op == "par":
        if len(args) < 1 or any(a.ty != "unit" for a in args):
            raise CompileError("par expects one or more unit expressions")
        return "unit"
    raise AssertionError(op)


def _asym_builtin_type(op: str, args: list[Expr]) -> str:
    sigs: dict[str, tuple[list[str], str]] = {
        "sub": (["i64", "i64"], "i64"),
        "div": (["i64", "i64"], "i64"),
        "mod": (["i64", "i64"], "i64"),
        "lt": (["i64", "i64"], "i1"),
        "le": (["i64", "i64"], "i1"),
        "concat": (["str", "str"], "str"),
        "startswith": (["str", "str"], "i1"),
        "contains": (["str", "str"], "i1"),
        "slice": (["str", "i64", "i64"], "str"),
        "charat": (["str", "i64"], "i64"),
        "replace": (["str", "str", "str"], "str"),
        "word": (["str", "i64"], "str"),
        "writefile": (["str", "str"], "i64"),
    }
    if op == "if":
        if len(args) != 3 or args[0].ty != "i1" or args[1].ty != args[2].ty:
            raise CompileError("if expects condition:i1 and two branches of the same type")
        return args[1].ty
    if op == "seq":
        if len(args) < 1:
            raise CompileError("seq expects at least one expression")
        return args[-1].ty
    exp, ret = sigs[op]
    if len(args) != len(exp):
        raise CompileError(f"{op} expects {len(exp)} operand(s), got {len(args)}")
    for i, (a, t) in enumerate(zip(args, exp)):
        if t != "poly" and a.ty != t:
            raise CompileError(f"{op} operand {i+1} expects {t}, got {a.ty}")
        if t == "poly" and a.ty not in {"i64", "i1", "str"}:
            raise CompileError(f"{op} cannot use {a.ty}")
    return ret


def resolve_expr(raw: Raw, ctx: ResolveContext) -> Expr:
    if isinstance(raw, Atom):
        if raw.kind == "int":
            return Expr(None, kind="int", value=raw.value, ty="i64", symmetry="atom")
        if raw.kind == "bool":
            return Expr(None, kind="bool", value=raw.value, ty="i1", symmetry="atom")
        if raw.kind == "string":
            return Expr(None, kind="string", value=raw.value, ty="str", symmetry="atom")
        name = str(raw.value)
        if name in ctx.locals:
            return Expr(None, kind="var", value=name, ty=ctx.locals[name], symmetry="atom")
        raise CompileError(f"unknown/bare symbol {name!r}")

    # A symbol is an operator iff it names a builtin or declared function.
    op_candidates: list[Atom] = []
    for x in raw.items:
        if isinstance(x, Atom) and x.kind == "symbol":
            n = str(x.value)
            if n in ALL_BUILTINS or n in ctx.program.funcs:
                op_candidates.append(x)
    if len(op_candidates) != 1:
        names = [str(x.value) for x in op_candidates]
        raise CompileError(f"brace expression must contain exactly one operator; found {names}")
    op_atom = op_candidates[0]
    op = str(op_atom.value)
    operand_raw = [x for x in raw.items if x is not op_atom]
    args = [resolve_expr(x, ctx) for x in operand_raw]

    if op in SYM_BUILTINS:
        args.sort(key=lambda e: e.canonical())
        ty = _sym_builtin_type(op, args)
        return Expr(op, tuple(args), ty=ty, symmetry="s")

    if op in ASYM_BUILTINS:
        ty = _asym_builtin_type(op, args)
        return Expr(op, tuple(args), ty=ty, symmetry="a")

    f = ctx.program.funcs[op]
    if len(args) != len(f.params):
        raise CompileError(f"{op} expects {len(f.params)} operands, got {len(args)}")
    if f.kind == "sfunc":
        # A symmetric function has a homogeneous domain; any operand can occupy
        # any formal slot. Sorting gives deterministic lowering.
        if f.params:
            pty = f.params[0][1]
            if any(a.ty != pty for a in args):
                raise CompileError(f"sfunc {op} expects all operands of type {pty}")
        args.sort(key=lambda e: e.canonical())
        return Expr(op, tuple(args), ty=f.ret, symmetry="s")

    # afunc: operator position is irrelevant, operand relative order is not.
    for i, (a, (_, pt)) in enumerate(zip(args, f.params)):
        if a.ty != pt:
            raise CompileError(f"afunc {op} operand {i+1} expects {pt}, got {a.ty}")
    ctx.program.warnings.append(f"warning: call to asymmetric function '{op}'")
    return Expr(op, tuple(args), ty=f.ret, symmetry="a")


def symbolic(expr: Expr, env: dict[str, str], program: Program) -> str:
    if expr.op is None:
        if expr.kind == "var":
            return env.get(str(expr.value), f"${expr.value}")
        if expr.kind == "string":
            return f"str:{expr.value!r}"
        if expr.kind == "bool":
            return "true" if expr.value else "false"
        return f"{expr.kind}:{expr.value}"
    parts = [symbolic(a, env, program) for a in expr.args]
    is_sym = expr.op in SYM_BUILTINS or (expr.op in program.funcs and program.funcs[expr.op].kind == "sfunc")
    if is_sym:
        parts.sort()
    return expr.op + "(" + ",".join(parts) + ")"


def verify_sfunc(f: FunctionDef, p: Program) -> None:
    if f.kind != "sfunc":
        return
    if len(f.params) > 1:
        tys = {t for _, t in f.params}
        if len(tys) != 1:
            raise CompileError(f"sfunc {f.name}: all parameters must have the same type to admit arbitrary permutations")
    if len(f.params) > 7:
        raise CompileError(f"sfunc {f.name}: arity {len(f.params)} exceeds MVP proof limit 7")
    assert f.body is not None
    if f.body.ty != f.ret:
        raise CompileError(f"{f.kind} {f.name}: declared return {f.ret}, body has {f.body.ty}")
    # Nullary/unary functions are permutation-invariant trivially.
    if len(f.params) <= 1:
        return
    # For recursive multi-arg sfuncs, treating the recursive call as symmetric
    # would be circular. Reject rather than pretend to prove it.
    def contains_self(e: Expr) -> bool:
        return (e.op == f.name) or any(contains_self(a) for a in e.args)
    if contains_self(f.body):
        raise CompileError(f"sfunc {f.name}: recursive symmetry proof is not implemented for arity > 1")

    names = [n for n, _ in f.params]
    base_env = {n: f"${n}" for n in names}
    baseline = symbolic(f.body, base_env, p)
    for perm in itertools.permutations(names):
        env = {n: f"${perm[i]}" for i, n in enumerate(names)}
        got = symbolic(f.body, env, p)
        if got != baseline:
            mapping = ", ".join(f"{n}->{perm[i]}" for i, n in enumerate(names))
            raise CompileError(
                f"sfunc {f.name} is not permutation-invariant; counterexample permutation {mapping}\n"
                f"  identity: {baseline}\n  permuted: {got}"
            )


def _collect_user_calls(e: Expr, p: Program) -> set[str]:
    out: set[str] = set()
    if e.op in p.funcs:
        out.add(e.op)
    for a in e.args:
        out |= _collect_user_calls(a, p)
    return out


def _reject_multiarity_sfunc_cycles(p: Program) -> None:
    graph: dict[str, set[str]] = {}
    for name, f in p.funcs.items():
        if f.kind == "sfunc" and f.body is not None:
            graph[name] = {x for x in _collect_user_calls(f.body, p) if p.funcs[x].kind == "sfunc"}

    index = 0
    stack: list[str] = []
    onstack: set[str] = set()
    indices: dict[str, int] = {}
    low: dict[str, int] = {}

    def strong(v: str) -> None:
        nonlocal index
        indices[v] = low[v] = index; index += 1
        stack.append(v); onstack.add(v)
        for w in graph.get(v, set()):
            if w not in indices:
                strong(w); low[v] = min(low[v], low[w])
            elif w in onstack:
                low[v] = min(low[v], indices[w])
        if low[v] == indices[v]:
            comp: list[str] = []
            while True:
                w = stack.pop(); onstack.remove(w); comp.append(w)
                if w == v: break
            cyclic = len(comp) > 1 or (len(comp) == 1 and comp[0] in graph.get(comp[0], set()))
            if cyclic and any(len(p.funcs[n].params) > 1 for n in comp):
                raise CompileError(
                    "cannot soundly prove permutation invariance for recursive/mutually recursive "
                    "multi-argument sfunc cycle: " + ", ".join(sorted(comp))
                )

    for v in graph:
        if v not in indices:
            strong(v)


def resolve_program(p: Program) -> Program:
    # Resolve bodies after all signatures are known.
    for f in p.funcs.values():
        locals_ = {n: t for n, t in f.params}
        f.body = resolve_expr(f.body_raw, ResolveContext(p, locals_, f.name))
        if f.body.ty != f.ret:
            raise CompileError(f"{f.kind} {f.name}: declared return {f.ret}, body has {f.body.ty}")
    # Verify after resolution so calls know callee kind. Reject recursive
    # multi-argument proof cycles rather than assuming the property we are
    # supposed to establish. Unary recursion is trivially symmetric.
    _reject_multiarity_sfunc_cycles(p)
    for f in p.funcs.values():
        verify_sfunc(f, p)
    p.main = resolve_expr(p.main_raw, ResolveContext(p, {}, None))  # type: ignore[arg-type]
    return p


class LLVMEmitter:
    def __init__(self, program: Program):
        self.p = program
        self.globals: list[str] = []
        self.string_globals: dict[str, tuple[str, int]] = {}
        self.temp = 0
        self.label = 0
        self.lines: list[str] = []
        self.env: dict[str, tuple[str, str]] = {}
        self.current_block = "entry"

    def fresh(self) -> str:
        x = f"%t{self.temp}"
        self.temp += 1
        return x

    def fresh_label(self, stem: str) -> str:
        x = f"{stem}.{self.label}"
        self.label += 1
        return x

    @staticmethod
    def llvm_ty(t: str) -> str:
        return {"i64": "i64", "i1": "i1", "str": "ptr", "unit": "void"}[t]

    @staticmethod
    def llvm_bytes(s: str) -> tuple[str, int]:
        b = s.encode("utf-8") + b"\0"
        pieces = []
        for x in b:
            if 32 <= x <= 126 and x not in (34, 92):
                pieces.append(chr(x))
            else:
                pieces.append(f"\\{x:02X}")
        return "".join(pieces), len(b)

    def intern_string(self, s: str) -> tuple[str, int]:
        if s in self.string_globals:
            return self.string_globals[s]
        h = hashlib.sha256(s.encode()).hexdigest()[:16]
        name = f"@.str.{h}"
        enc, n = self.llvm_bytes(s)
        self.globals.append(f'{name} = private unnamed_addr constant [{n} x i8] c"{enc}"')
        self.string_globals[s] = (name, n)
        return name, n

    def emit(self, line: str) -> None:
        self.lines.append("  " + line)

    def emit_expr(self, e: Expr) -> tuple[str, str]:
        if e.op is None:
            if e.kind == "int":
                return "i64", str(e.value)
            if e.kind == "bool":
                return "i1", "1" if e.value else "0"
            if e.kind == "string":
                name, n = self.intern_string(str(e.value))
                t = self.fresh()
                self.emit(f"{t} = getelementptr [{n} x i8], ptr {name}, i64 0, i64 0")
                return "ptr", t
            if e.kind == "var":
                return self.env[str(e.value)]
            raise AssertionError(e)

        op = e.op
        if op == "par":
            # Commutative effect join. The compiler canonicalizes children, so
            # source permutation cannot affect generated execution order. Use
            # this only for effects whose observable meaning is a multiset.
            for a in e.args:
                self.emit_expr(a)
            return "void", ""

        # `choose` is an order-free conditional: alternatives are an unordered
        # set of guarded values and exactly one guard must hold.
        if op == "choose":
            choices = []
            for c in e.args:
                assert c.op == "when"
                cond = next(a for a in c.args if a.ty == "i1")
                val = next(a for a in c.args if a.ty in {"i64", "str"})
                ct, cv = self.emit_expr(cond)
                vt, vv = self.emit_expr(val)
                choices.append((cv, vt, vv))
            count = "0"
            for cv, _, _ in choices:
                z = self.fresh(); self.emit(f"{z} = zext i1 {cv} to i64")
                a = self.fresh(); self.emit(f"{a} = add i64 {count}, {z}")
                count = a
            self.emit(f"call void @sn_choice_check(i64 {count})")
            out_ty = choices[0][1]
            # Unique-true semantics makes the source order irrelevant. Start
            # from the first value; subsequent selects can only replace it at
            # the one true guard.
            out = choices[0][2]
            for cv, _, vv in choices[1:]:
                t = self.fresh(); self.emit(f"{t} = select i1 {cv}, {out_ty} {vv}, {out_ty} {out}")
                out = t
            return out_ty, out
        if op == "when":
            raise CompileError("guarded `when` value may only appear inside `choose`")

        # Lazy ordered control forms.
        if op == "if":
            cond_t, cond_v = self.emit_expr(e.args[0])
            then_label = self.fresh_label("then")
            else_label = self.fresh_label("else")
            merge_label = self.fresh_label("merge")
            self.emit(f"br i1 {cond_v}, label %{then_label}, label %{else_label}")
            self.lines.append(f"{then_label}:")
            self.current_block = then_label
            tt, tv = self.emit_expr(e.args[1])
            then_end = self.current_block
            self.emit(f"br label %{merge_label}")
            self.lines.append(f"{else_label}:")
            self.current_block = else_label
            et, ev = self.emit_expr(e.args[2])
            else_end = self.current_block
            self.emit(f"br label %{merge_label}")
            self.lines.append(f"{merge_label}:")
            self.current_block = merge_label
            if e.ty == "unit":
                return "void", ""
            out = self.fresh()
            self.emit(f"{out} = phi {tt} [{tv}, %{then_end}], [{ev}, %{else_end}]")
            return tt, out

        if op == "seq":
            last = ("void", "")
            for a in e.args:
                last = self.emit_expr(a)
            return last

        if op == "print":
            at, av = self.emit_expr(e.args[0])
            if e.args[0].ty == "str":
                self.emit(f"call i32 @puts(ptr {av})")
            elif e.args[0].ty == "i64":
                self.emit(f"call i32 (ptr, ...) @printf(ptr @.fmt_i64, i64 {av})")
            elif e.args[0].ty == "i1":
                z = self.fresh()
                self.emit(f"{z} = zext i1 {av} to i32")
                self.emit(f"call i32 (ptr, ...) @printf(ptr @.fmt_i1, i32 {z})")
            return "void", ""

        if op == "readline":
            t = self.fresh(); self.emit(f"{t} = call ptr @sn_readline()"); return "ptr", t
        if op == "argc":
            t = self.fresh(); self.emit(f"{t} = call i64 @sn_argc()"); return "i64", t

        vals = [self.emit_expr(a) for a in e.args]
        if op == "b2i":
            t = self.fresh(); self.emit(f"{t} = zext i1 {vals[0][1]} to i64"); return "i64", t

        if op in {"add", "mul", "and", "or", "xor"}:
            opcode = op
            ty = "i64" if op in {"add", "mul"} else "i1"
            acc = vals[0][1]
            for _, v in vals[1:]:
                t = self.fresh(); self.emit(f"{t} = {opcode} {ty} {acc}, {v}"); acc = t
            return ty, acc
        if op == "nand":
            a, b = vals[0][1], vals[1][1]
            t1 = self.fresh(); self.emit(f"{t1} = and i1 {a}, {b}")
            t2 = self.fresh(); self.emit(f"{t2} = xor i1 {t1}, 1")
            return "i1", t2
        if op == "eq":
            a, b = vals[0][1], vals[1][1]
            if e.args[0].ty == "str":
                t = self.fresh(); self.emit(f"{t} = call i1 @sn_streq(ptr {a}, ptr {b})"); return "i1", t
            ty = self.llvm_ty(e.args[0].ty)
            t = self.fresh(); self.emit(f"{t} = icmp eq {ty} {a}, {b}"); return "i1", t
        if op in {"sub", "div", "mod"}:
            opcode = {"sub":"sub", "div":"sdiv", "mod":"srem"}[op]
            t = self.fresh(); self.emit(f"{t} = {opcode} i64 {vals[0][1]}, {vals[1][1]}"); return "i64", t
        if op in {"lt", "le"}:
            pred = "slt" if op == "lt" else "sle"
            t = self.fresh(); self.emit(f"{t} = icmp {pred} i64 {vals[0][1]}, {vals[1][1]}"); return "i1", t

        runtime_calls: dict[str, tuple[str, list[str]]] = {
            "concat": ("@sn_concat", ["ptr", "ptr"]),
            "startswith": ("@sn_startswith", ["ptr", "ptr"]),
            "contains": ("@sn_contains", ["ptr", "ptr"]),
            "slice": ("@sn_slice", ["ptr", "i64", "i64"]),
            "charat": ("@sn_charat", ["ptr", "i64"]),
            "strlen": ("@sn_strlen", ["ptr"]),
            "trim": ("@sn_trim", ["ptr"]),
            "replace": ("@sn_replace", ["ptr", "ptr", "ptr"]),
            "word": ("@sn_word", ["ptr", "i64"]),
            "wordcount": ("@sn_wordcount", ["ptr"]),
            "firstline": ("@sn_firstline", ["ptr"]),
            "restlines": ("@sn_restlines", ["ptr"]),
            "readfile": ("@sn_readfile", ["ptr"]),
            "writefile": ("@sn_writefile", ["ptr", "ptr"]),
            "arg": ("@sn_arg", ["i64"]),
            "itoa": ("@sn_itoa", ["i64"]),
            "atoi": ("@sn_atoi", ["ptr"]),
        }
        if op in runtime_calls:
            fn, tys = runtime_calls[op]
            ret_ty = self.llvm_ty(e.ty)
            av = ", ".join(f"{t} {v}" for t, (_, v) in zip(tys, vals))
            t = self.fresh()
            self.emit(f"{t} = call {ret_ty} {fn}({av})")
            return ret_ty, t

        # user-defined function
        if op in self.p.funcs:
            f = self.p.funcs[op]
            ret_ty = self.llvm_ty(f.ret)
            parts = []
            for (_, pt), (_, v) in zip(f.params, vals):
                parts.append(f"{self.llvm_ty(pt)} {v}")
            call = f"call {ret_ty} @sn_{f.name}(" + ", ".join(parts) + ")"
            if ret_ty == "void":
                self.emit(call)
                return "void", ""
            t = self.fresh(); self.emit(f"{t} = {call}"); return ret_ty, t

        raise AssertionError(op)

    def function_ir(self, f: FunctionDef) -> list[str]:
        self.lines = []; self.temp = 0; self.label = 0; self.current_block = "entry"
        self.env = {n: (self.llvm_ty(t), f"%{n}") for n, t in f.params}
        params = ", ".join(f"{self.llvm_ty(t)} %{n}" for n, t in f.params)
        out = [f"define {self.llvm_ty(f.ret)} @sn_{f.name}({params}) {{", "entry:"]
        assert f.body is not None
        ty, val = self.emit_expr(f.body)
        out.extend(self.lines)
        if f.ret == "unit": out.append("  ret void")
        else: out.append(f"  ret {self.llvm_ty(f.ret)} {val}")
        out.append("}")
        return out

    def module(self) -> str:
        # Emit all functions first; string globals are accumulated while doing so.
        fblocks: list[list[str]] = []
        for f in self.p.funcs.values():
            fblocks.append(self.function_ir(f))
        self.lines = []; self.temp = 0; self.label = 0; self.env = {}; self.current_block = "entry"
        assert self.p.main is not None
        self.emit_expr(self.p.main)
        main_lines = list(self.lines)

        prelude = [
            "; generated by snc.py (Sn MVP v1)",
            '@.fmt_i64 = private unnamed_addr constant [5 x i8] c"%ld\\0A\\00"',
            '@.fmt_i1 = private unnamed_addr constant [4 x i8] c"%d\\0A\\00"',
            *self.globals,
            "",
            "declare i32 @printf(ptr, ...)",
            "declare i32 @puts(ptr)",
            "declare i1 @sn_streq(ptr, ptr)",
            "declare ptr @sn_concat(ptr, ptr)",
            "declare i1 @sn_startswith(ptr, ptr)",
            "declare i1 @sn_contains(ptr, ptr)",
            "declare ptr @sn_slice(ptr, i64, i64)",
            "declare i64 @sn_charat(ptr, i64)",
            "declare i64 @sn_strlen(ptr)",
            "declare ptr @sn_trim(ptr)",
            "declare ptr @sn_replace(ptr, ptr, ptr)",
            "declare ptr @sn_word(ptr, i64)",
            "declare i64 @sn_wordcount(ptr)",
            "declare ptr @sn_firstline(ptr)",
            "declare ptr @sn_restlines(ptr)",
            "declare ptr @sn_readfile(ptr)",
            "declare i64 @sn_writefile(ptr, ptr)",
            "declare ptr @sn_arg(i64)",
            "declare i64 @sn_argc()",
            "declare ptr @sn_readline()",
            "declare ptr @sn_itoa(i64)",
            "declare i64 @sn_atoi(ptr)",
            "declare void @sn_choice_check(i64)",
            "declare void @sn_set_args(i32, ptr)",
            "",
        ]
        out = prelude
        for b in fblocks:
            out += b + [""]
        out += ["define i32 @main(i32 %argc, ptr %argv) {", "entry:",
                "  call void @sn_set_args(i32 %argc, ptr %argv)"]
        out += main_lines + ["  ret i32 0", "}", ""]
        return "\n".join(out)


def asymmetric_uses(p: Program) -> list[str]:
    uses: list[str] = []
    if any(f.kind == "afunc" for f in p.funcs.values()):
        uses.extend(f"afunc declaration '{f.name}'" for f in p.funcs.values() if f.kind == "afunc")
    def walk(e: Expr | None, where: str) -> None:
        if e is None:
            return
        if e.op in ASYM_BUILTINS:
            uses.append(f"asymmetric primitive '{e.op}' in {where}")
        if e.op in p.funcs and p.funcs[e.op].kind == "afunc":
            uses.append(f"afunc call '{e.op}' in {where}")
        for a in e.args:
            walk(a, where)
    for f in p.funcs.values():
        walk(f.body, f"{f.kind} {f.name}")
    walk(p.main, "main")
    return uses


def compile_source(src: str, *, symmetric_only: bool = False) -> tuple[Program, str]:
    p = resolve_program(parse_program(src))
    if symmetric_only:
        bad = asymmetric_uses(p)
        if bad:
            raise CompileError("symmetric-only build rejected:\n  " + "\n  ".join(bad))
    llvm = LLVMEmitter(p).module()
    return p, llvm


def main() -> int:
    ap = argparse.ArgumentParser(prog="snc", description="Sn permutation-aware compiler -> LLVM IR")
    ap.add_argument("source")
    ap.add_argument("-o", "--output", default="-")
    ap.add_argument("--ast", action="store_true")
    ap.add_argument("--deny-warnings", action="store_true")
    ap.add_argument("--symmetric-only", action="store_true", help="reject afuncs and asymmetric primitives")
    ns = ap.parse_args()
    try:
        src = sys.stdin.read() if ns.source == "-" else Path(ns.source).read_text()
        p, llvm = compile_source(src, symmetric_only=ns.symmetric_only)
        for w in p.warnings:
            print(w, file=sys.stderr)
        if ns.deny_warnings and p.warnings:
            raise CompileError("warnings denied")
        if ns.ast:
            for f in p.funcs.values():
                print(f"{f.kind} {f.name} = {f.body.canonical() if f.body else '?'}", file=sys.stderr)
            print(f"main = {p.main.canonical() if p.main else '?'}", file=sys.stderr)
        if ns.output == "-": sys.stdout.write(llvm)
        else: Path(ns.output).write_text(llvm)
        return 0
    except (OSError, CompileError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
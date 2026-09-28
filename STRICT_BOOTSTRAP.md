# The strict-bootstrap puzzle

The goal is stronger than “all declarations are spelled `sfunc`.” A compiler can
fake that by hiding order-sensitive work in unary helpers or builtins such as
`concat`, `word`, `if`, or `writefile`. Sn v2 therefore has:

```bash
snc.py program.sn --symmetric-only
```

This rejects every `afunc` and every primitive whose semantics depends on
operand roles/order. The old `bootstrap/snc_core.sn` intentionally fails this
audit. That is a feature: the compiler now detects the loophole instead of
calling it symmetry.

## What works strictly

`examples/adventure_sfunc.sn` passes the strict audit. It uses only `sfunc`s and
symmetric intrinsics. Its four textual events carry timestamps such as
`1:north` and `4:unlock`; the four event arguments themselves are an unordered
multiset. All 24 argv permutations produce the same ending. Chronology lives in
the data, not in function argument position.

`bootstrap/symmetric_kernel.sn` is a strict symmetric compiler *kernel* for the
original four-token arithmetic demo. The tokens `print`, `add`, `20`, `22` may
arrive in any order. The kernel emits an unordered bag of IR facts. A tiny
trusted serializer (`bootstrap/ir_serializer.py`) turns that graph/fact bag into
ordered textual LLVM. All 24 input permutations produce byte-identical LLVM.

## Why the serializer is explicit

LLVM `.ll` is an ordered byte string. If a supposedly pure symmetric compiler
uses ordered concatenation internally to manufacture that string, the ordering
has merely been hidden. The honest architecture is:

```
unordered Sn source semantics
        ↓
symmetric compiler / lowering
        ↓
unordered LLVM semantic graph or fact bag
        ↓
trusted canonical serializer
        ↓
ordered .ll bytes
```

The serializer is deliberately outside the claim. It is analogous to choosing a
canonical textual representation for an unordered mathematical object.

## What is *not* solved yet

The strict kernel is not yet a full fixed-point self-host. The older Sn-written
stage-1 compiler can compile the original flat core, but it cannot compile its
own full source; and it fails the strict primitive audit. A genuine next
milestone is a generic unordered AST/IR representation plus enough symmetric
pattern/rewrite machinery that the Sn compiler core can lower its own AST.

A full fixed point should require:

1. stage 0 compiles `snc.sn` -> stage 1;
2. stage 1 compiles the same `snc.sn` -> stage 2;
3. stage-1 and stage-2 semantic IR are identical (or canonical LLVM is
   byte-identical);
4. `snc.sn --symmetric-only` reports zero asymmetric uses.

Anything weaker should not be advertised as the completed strict bootstrap.
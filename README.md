# Sn MVP v2 — checked symmetric functions -> LLVM

Sn (`.sn`, after the symmetric group `S_n`) is a small compiler experiment in
which source position is not allowed to silently assign semantic roles.

```sn
sfunc sum2(a:i64,b:i64) -> i64 = { add a b };
afunc difference(a:i64,b:i64) -> i64 = { sub a b };
```

(`afunc` above is spelled normally in real files; the zero-width break is only
here to stop some Markdown renderers treating the example as a link.)

## `sfunc` and `afunc`

For a multi-argument `sfunc`, the compiler symbolically checks every permutation
of the formal parameters. The normalized body must be identical. This passes:

```sn
sfunc sum2(a:i64,b:i64) -> i64 = { add a b };
```

This is rejected with a counterexample permutation:

```sn
sfunc bad(a:i64,b:i64) -> i64 = { sub a b };
```

Calls to an `afunc` compile but emit a warning. `--deny-warnings` turns those
warnings into errors.

## Symmetric intrinsics

The symmetric prelude includes the genuinely commutative operations (`add`,
`mul`, Boolean operators, `eq`, `nand`) and nullary/unary operations such as
`print`, `arg`, `readline`, `strlen`, `trim`, `itoa`, and `atoi`. Unary `print`
is therefore explicitly classified as a symmetric intrinsic rather than being
quietly left outside the model.

Order-sensitive primitives (`concat`, `sub`, `if`, `seq`, `word`, `writefile`,
etc.) still exist for ordinary programs, but:

```bash
python3 snc.py file.sn --symmetric-only
```

rejects every use of them and every `afunc`.

## Order-free conditional

v2 adds an unordered guarded-choice form:

```sn
sfunc label(x:i64) -> str = { choose
    { when { eq x 1 } "one" }
    { when { eq x 2 } "two" }
};
```

`choose` treats its alternatives as a multiset and requires exactly one guard to
be true at runtime. Source order of the alternatives carries no meaning.

`par` is a commutative join for unit effects whose observable meaning is itself a
multiset (used by the compiler-kernel fact stream).

## Strict all-`sfunc` adventure

Build:

```bash
make adventure-symmetric
```

Run the winning transcript:

```bash
./adventure_sfunc '3:south' '1:north' '4:unlock' '2:key'
```

Output:

```text
You unlock the cellar door and escape. You win.
```

All **24 permutations** of those four argv values produce the same result. The
turn numbers are part of the event data, so chronology is reconstructed without
using argument position. The source contains 14 user functions, all `sfunc`, and
passes `--symmetric-only` with zero asymmetric uses.

## Strict compiler kernel -> LLVM

Build and run:

```bash
make kernel
```

The Sn-written `bootstrap/symmetric_kernel.sn` accepts the four source facts
`print add 20 22` in any order, emits an unordered IR fact bag, and the tiny
trusted `bootstrap/ir_serializer.py` canonicalizes that bag into LLVM. All 24
token permutations produce byte-identical LLVM, and the resulting native program
prints `42`.

The explicit serializer boundary matters: textual LLVM is ordered, and hiding
ordered `concat` inside the compiler would merely smuggle the asymmetry back in.
See `STRICT_BOOTSTRAP.md`.

## Bootstrap status

There are now two bootstrap experiments:

- `bootstrap/snc_core.sn`: an older Sn-written stage-1 compiler seed. Every user
  declaration is an `sfunc`, but the new strict audit correctly exposes its use
  of ordered parser/string primitives. It is **not** a strict solution.
- `bootstrap/symmetric_kernel.sn`: passes the strict audit and produces LLVM via
  an explicit canonical serializer, but is currently only a small compiler
  kernel, **not a full stage-1 -> stage-2 fixed-point self-host**.

That distinction is intentional. See `STRICT_BOOTSTRAP.md` for the exact next
criterion instead of pretending the harder bootstrap is already solved.

## Tests

```bash
make test
```

The tests cover symmetry proof/rejection, `afunc` warnings, identical LLVM for
source permutations, native Clang execution, the historical bootstrap, strict
primitive auditing, all 24 adventure permutations, and all 24 strict compiler
kernel permutations.
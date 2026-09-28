# Sn

**Sn is an experimental programming language where source-code order is not supposed to carry meaning unless you explicitly ask for it.**

The name comes from the symmetric group \(S_n\), the group of all permutations of \(n\) things. Sn source files use the extension `.sn`.

The motivating example is deliberately silly:

```sn
{ print "hello world" }
```

and

```sn
{ "hello world" print }
```

should mean the same thing.

The real question is much more interesting:

> How much programming can we do if swapping the pieces of an expression is forbidden from changing its meaning?

Sn is a prototype for exploring that question. It compiles to LLVM IR.

---

## The basic idea

Most programming languages give meaning to position:

```text
subtract(10, 3)
```

Here, the first argument and the second argument have different roles.

Sn tries to remove that hidden source of asymmetry. For symmetric code, expressions are treated as unordered collections of terms. Reordering those terms must not change the result.

For example:

```sn
{ add 20 22 }
{ 22 add 20 }
{ 20 22 add }
```

all describe the same symmetric computation.

Internally, the compiler resolves the expression, canonicalizes it, and then emits ordinary LLVM IR. LLVM does not need to know that the source language was order-free.

```text
Sn source
   ↓
unordered / symmetric resolution
   ↓
canonical semantic form
   ↓
LLVM IR
   ↓
native code
```

---

## `sfunc`: functions that must actually be symmetric

Sn has two kinds of user-defined functions.

A **symmetric function** is declared with `sfunc`:

```sn
sfunc sum2(a:i64, b:i64) -> i64 = { add a b };
```

For the supported pure subset, the compiler checks that permuting the parameters does not change the normalized meaning of the function.

So this is accepted:

```sn
sfunc sum2(a:i64, b:i64) -> i64 = { add a b };
```

because

```text
sum2(a, b) = sum2(b, a)
```

But this is rejected:

```sn
sfunc bad(a:i64, b:i64) -> i64 = { sub a b };
```

because subtraction is not permutation-invariant.

That rejection is the point. `sfunc` is not a promise made by the programmer; it is a property the compiler tries to verify.

---

## `afunc`: an explicit escape hatch

Some computations really are asymmetric.

For those, Sn has `afunc`:

```sn
afunc difference(a:i64, b:i64) -> i64 = { sub a b };
```

This is allowed, but every use of an `afunc` emits a compiler warning.

The idea is to make asymmetry visible instead of silently encoding it through argument order.

If you want to forbid asymmetric code entirely:

```bash
python3 snc.py program.sn --symmetric-only --deny-warnings
```

That mode rejects `afunc` and order-sensitive primitives.

---

## Symmetric primitives

Sn currently has a small symmetric core including operations such as:

```text
add
mul
and
or
xor
nand
eq
print
```

Binary operations such as `add` and `nand` are genuinely commutative.

Unary operations such as `print` are trivially symmetric because there is only one argument to permute.

Order-sensitive operations such as subtraction, string concatenation, sequencing, positional indexing, and ordinary `if(condition, then, else)` are treated as asymmetric.

---

## Branching without ordered arguments

Ordinary conditionals secretly have three positional roles:

```text
if(condition, then_branch, else_branch)
```

Sn experiments with an unordered guarded-choice form instead:

```sn
sfunc label(x:i64) -> str = { choose
    { when { eq x 1 } "one" }
    { when { eq x 2 } "two" }
};
```

The alternatives form an unordered collection. At runtime, exactly one guard must be true.

Reordering the `when` clauses does not change the program.

---

## A fully symmetric demo

`examples/adventure_sfunc.sn` is a tiny text-adventure state machine written using only `sfunc` declarations.

Build it with:

```bash
make adventure-symmetric
```

Then run:

```bash
./adventure_sfunc '3:south' '1:north' '4:unlock' '2:key'
```

It prints:

```text
You unlock the cellar door and escape. You win.
```

The four events can be supplied in any of their **24 possible argument orders** and the result is identical.

The trick is important: chronology is stored in the event values (`1:north`, `2:key`, ...), rather than being inferred from argument position.

So the data can contain structure while the function itself remains symmetric.

---

## Why LLVM?

Sn's unusual part is the frontend, not machine-code generation.

Once an Sn expression has been resolved into a canonical semantic form, the compiler emits normal LLVM IR and lets LLVM/Clang handle the boring backend work.

For example:

```bash
python3 snc.py examples/functions.sn -o program.ll
clang program.ll runtime.c -o program
./program
```

This keeps the experiment focused on the actual question: **can useful programs be expressed without making textual position semantically important?**

---

## The self-hosting challenge

The long-term challenge is to write the Sn compiler in Sn itself while using only symmetric functions.

This is harder than it first appears.

A fake solution would hide ordering inside helpers such as:

```text
concat(left, right)
word(text, position)
writefile(path, contents)
```

and then wrap those helpers inside unary `sfunc` declarations. That technically passes a superficial "all functions are symmetric" test while smuggling positional semantics back in.

We explicitly reject that trick.

The current strict bootstrap experiment is:

```text
Sn compiler kernel
      ↓
unordered semantic IR facts
      ↓
tiny canonical serializer
      ↓
LLVM text
```

`bootstrap/symmetric_kernel.sn` passes the strict symmetric audit and accepts the source facts

```text
print add 20 22
```

in any order. Every permutation produces the same semantic IR and the same LLVM program, which prints:

```text
42
```

The final serializer is intentionally a small trusted boundary because LLVM text itself is an ordered byte stream.

A **full fixed-point self-hosted compiler is not implemented yet**. See [STRICT_BOOTSTRAP.md](STRICT_BOOTSTRAP.md) for the exact standard we are aiming for.

---

## Try it

Requirements:

- Python 3
- Clang / LLVM
- Make

Run the tests:

```bash
make test
```

Build the strict symmetric adventure:

```bash
make adventure-symmetric
```

Run the strict compiler-kernel demo:

```bash
make kernel
```

---

## Project status

Sn is currently a research toy / language-design prototype, not a production programming language.

What works today:

- `.sn` source files
- LLVM IR generation
- user-defined `sfunc` and `afunc`
- compiler errors for non-symmetric `sfunc` definitions in the supported subset
- warnings for `afunc` calls
- strict symmetric-only compilation
- unordered guarded choice
- native programs via Clang
- an all-`sfunc` adventure demo
- a strict symmetric compiler kernel

What is still open:

- a richer type system
- serious data structures
- a principled model of effects
- more scalable symmetry proofs
- a full self-hosted Sn compiler
- figuring out how far this programming model can go before asymmetry becomes unavoidable

That last question is the reason this project exists.

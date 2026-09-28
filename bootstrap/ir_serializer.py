#!/usr/bin/env python3
"""Tiny trusted boundary: unordered Sn IR facts -> textual LLVM IR.

This is intentionally not part of the Sn semantic compiler. LLVM syntax is an
ordered byte stream; this serializer is the explicit place where an order is
chosen. Input fact order is ignored.
"""
import sys
facts=[x.strip() for x in sys.stdin if x.strip()]
if 'IR:error' in facts or 'IR:print-i64' not in facts:
    raise SystemExit('invalid Sn IR fact bag')
nums=[]
for f in facts:
    try: nums.append(int(f))
    except ValueError: pass
if len(nums)!=1:
    raise SystemExit(f'expected exactly one integer fact, got {nums!r}')
n=nums[0]
print('; serialized from unordered Sn IR facts')
print('@.fmt = private unnamed_addr constant [5 x i8] c"%ld\\0A\\00"')
print('declare i32 @printf(ptr, ...)')
print('define i32 @main() {')
print('entry:')
print(f'  call i32 (ptr, ...) @printf(ptr @.fmt, i64 {n})')
print('  ret i32 0')
print('}')
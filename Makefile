PYTHON ?= python3
CLANG ?= clang

.PHONY: test adventure-symmetric kernel bootstrap clean

test:
	$(PYTHON) tests/test_sfuncs.py
	$(PYTHON) tests/test_end_to_end.py
	$(PYTHON) tests/test_symmetric_strict.py

adventure-symmetric: adventure_sfunc

adventure_sfunc.ll: examples/adventure_sfunc.sn snc.py
	$(PYTHON) snc.py $< -o $@ --symmetric-only --deny-warnings

adventure_sfunc: adventure_sfunc.ll runtime.c
	$(CLANG) adventure_sfunc.ll runtime.c -o adventure_sfunc

bootstrap/symmetric_kernel.ll: bootstrap/symmetric_kernel.sn snc.py
	$(PYTHON) snc.py $< -o $@ --symmetric-only --deny-warnings

bootstrap/symmetric_kernel: bootstrap/symmetric_kernel.ll runtime.c
	$(CLANG) bootstrap/symmetric_kernel.ll runtime.c -o bootstrap/symmetric_kernel

kernel: bootstrap/symmetric_kernel
	./bootstrap/symmetric_kernel 22 print 20 add | $(PYTHON) bootstrap/ir_serializer.py > bootstrap/kernel_out.ll
	$(CLANG) bootstrap/kernel_out.ll -o bootstrap/kernel_out
	./bootstrap/kernel_out

# Historical stage-1 seed: all user declarations are sfunc, but strict auditing
# correctly rejects its ordered string/parser primitives. Kept for comparison.
bootstrap/snc_core.ll: bootstrap/snc_core.sn snc.py
	$(PYTHON) snc.py $< -o $@ --deny-warnings

bootstrap/snc_core: bootstrap/snc_core.ll runtime.c
	$(CLANG) bootstrap/snc_core.ll runtime.c -o bootstrap/snc_core

bootstrap: bootstrap/snc_core
	./bootstrap/snc_core bootstrap/example_core.sn bootstrap/example_core.ll
	$(CLANG) bootstrap/example_core.ll -o bootstrap/example_core
	./bootstrap/example_core

clean:
	rm -f adventure_sfunc adventure_sfunc.ll bootstrap/symmetric_kernel bootstrap/symmetric_kernel.ll bootstrap/kernel_out bootstrap/kernel_out.ll bootstrap/snc_core bootstrap/snc_core.ll bootstrap/example_core bootstrap/example_core.ll

#!/usr/bin/env python3
"""build_omok.py — omok_ai.py 를 소스 수정 없이 Cython C 확장(.so)으로 컴파일.
로직 그대로, 속도만. 실행: python3 build_omok.py build_ext --inplace
결과 omok_ai.*.so 가 omok_ai.py 를 가려 import 시 컴파일본이 쓰인다."""
from setuptools import setup
from Cython.Build import cythonize

setup(
    name="omok_ai_cy",
    ext_modules=cythonize(
        "omok_ai.py",
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
            "cdivision": True,
            "infer_types": True,
            "initializedcheck": False,
        },
        annotate=False,
        quiet=True,
    ),
)

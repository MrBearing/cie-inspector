from setuptools import setup

setup(
    name="py_pkg",
    version="0.1.0",
    packages=["py_pkg"],
    entry_points={
        "console_scripts": [
            "py_talker = py_pkg.talker:main",
        ],
    },
)

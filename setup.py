"""Build shim: the application version lives in the repo-root VERSION file.

VERSION keeps a human-friendly "v" prefix (e.g. "v2.0.0-beta.12") so it matches
the Git tag. Distribution metadata must be PEP 440-valid, so we strip the
leading "v" here. The frontend and API always derive the displayed version from
this same file via the package metadata, never from deploy-time variables.
"""
from setuptools import setup

setup(version=open("VERSION").read().strip().lstrip("v"))

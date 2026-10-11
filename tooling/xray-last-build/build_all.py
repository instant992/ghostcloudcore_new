"""Portable entry point; pins are explicit and publication is never performed here."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core-ci'))
from pipeline import build

p = argparse.ArgumentParser()
p.add_argument('--metadata', type=Path, required=True, help='Resolved release JSON with exact commit SHA')
p.add_argument('--ndk', type=Path, required=True)
p.add_argument('--work', type=Path, required=True, help='Must not already exist')
p.add_argument('--output', type=Path, required=True)
p.add_argument('--go', default='go')
a = p.parse_args()
build('xray-last', a.metadata.resolve(), Path(__file__).resolve().parents[1], a.work.resolve(), a.output.resolve(), a.ndk.resolve(), a.go)

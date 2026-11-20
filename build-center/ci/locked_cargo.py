#!/usr/bin/env python3
"""Enforce --locked in upstream Gradle's cargo and cargo-ndk build invocations."""
import os
import sys

arguments=sys.argv[1:]
if 'build' in arguments and '--locked' not in arguments:
    arguments.insert(arguments.index('build')+1,'--locked')
os.execv(os.environ['BUILTZYGISK_CARGO'],[os.environ['BUILTZYGISK_CARGO'],*arguments])

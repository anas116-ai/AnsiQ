"""AnsiQ — Intelligent Agent Orchestration Framework.

A unified open-source framework combining multi-agent orchestration,
persistent memory, skill learning, and universal LLM support.
"""

import logging

__version__ = "0.1.0"
__author__ = "AnsiQ Team"
__description__ = "Intelligent Agent Orchestration Framework"

# Library best-practice: attach a NullHandler to the package logger so that
# log records emitted by ``ansiq.*`` submodules do not leak to the root
# logger (and therefore to stderr) when the consuming application has not
# configured logging.  See https://docs.python.org/3/howto/logging.html
# "Configuring Logging for a Library".
logging.getLogger("ansiq").addHandler(logging.NullHandler())

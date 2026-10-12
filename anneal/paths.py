"""Where Anneal keeps your files. Set ANNEAL_HOME to move everything somewhere else."""
import os


def home():
    return os.environ.get("ANNEAL_HOME") or os.path.join(os.path.expanduser("~"), "Anneal Projects")

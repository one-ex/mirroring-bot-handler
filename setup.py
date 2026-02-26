"""Setup file for the bot application."""

import sys
import os

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import all necessary modules
from config import Config
from poller import start_poller
from web.app import app

__all__ = ['Config', 'start_poller', 'app']
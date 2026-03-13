# -*- coding: utf-8 -*-
"""
AI Providers для INTELLECTUM
Модульная система с поддержкой разных AI-моделей
"""

from .base import AIProvider
from .claude_provider import ClaudeProvider

__all__ = ["AIProvider", "ClaudeProvider"]

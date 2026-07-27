"""The graphical application: wiring, widgets and presentation. No business rules.

This is the only package in the product allowed to import ``PySide6`` (SPEC
NFR-2), and ``app.py`` is the only module in the product that constructs an
adapter (SPEC NFR-3). Presentation logic lives in ``view_models.py``, in plain
Python, so it can be tested without a ``QApplication``.
"""

"""GUI-agnostic measurement engine for the Trap Tester.

This package contains no Qt (or any GUI) imports. The measurement functions
are driven through a :class:`~trap_tester.core.reporter.MeasurementContext`
that supplies the hardware device, the settings, a reporter (for status / log
/ live scope captures / per-pin results) and a gate (for the interactive
retake / continue prompts that used to be blocking ``input()`` calls).
"""

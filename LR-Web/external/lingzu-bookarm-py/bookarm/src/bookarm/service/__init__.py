"""HTTP take-out/return service for the bookarm workflows.

The subpackage is intentionally import-light: ``runner`` and ``schemas`` only
depend on the transport-neutral bookarm API, while ``app`` and ``__main__``
require the optional ``service`` dependencies (fastapi, uvicorn,
python-multipart). ``studio`` implements the spine workbench (capture, manual
crop, template library) on the camera/lift device services. ``composition``
additionally imports the device drivers, so ``__main__`` only loads it for
real-hardware runs.
"""

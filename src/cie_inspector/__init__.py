"""Static extraction of ROS 2 callback/CallbackGroup structure from source code."""

# Single place that defines how this package names itself.  The "cie_" prefix
# is fixed; the suffix may still change before release, so nothing else in the
# codebase should hard-code these strings — import them from here.
PACKAGE_NAME = "cie_inspector"
CLI_NAME = "cie-inspector"
SCHEMA_VERSION = "0.1"
__version__ = "0.1.0"

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("duvo-sandstorm")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"


def __getattr__(name: str):
    if name == "app":
        from .main import app

        return app
    if name == "SandstormClient":
        from .client import SandstormClient

        return SandstormClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

__all__ = ["app", "SandstormClient", "__version__"]

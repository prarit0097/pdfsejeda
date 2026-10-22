Optional Python wheels for restricted/slow server networks go here. Wheel files
are ignored by Git but available to the Docker build through a temporary bind
mount; the final image does not retain a separate wheelhouse layer.

Download every pinned wheel from the official PyPI index for the target Linux
architecture and Python version. Set `PDFNOVA_PYTHON_OFFLINE=1` only when this
directory contains all required compatible wheels. No index is consulted in that
mode. With the default value `0`, normal index installation remains available.

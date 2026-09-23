#!/usr/bin/env bash
# Reconstructed from a Jetson Nano's ~/.bash_history (Phase 22 inventory
# session, 2026-09-22). Builds a working reachy_mini SDK + reachy-mini-daemon
# environment on a JetPack 4 / Ubuntu 18.04 (Bionic) Jetson Nano, where apt's
# Python tops out at 3.6 and the distro's GStreamer is too old for the
# daemon's media pipeline.
#
# NOT YET RE-RUN END TO END. The Nano this was transcribed from already had
# a working reachy-venv/gstreamer/gst-plugins-rs from a prior manual session,
# and rebuilding everything (Python from source + GStreamer from source +
# gst-plugins-rs from source) takes a long time on Nano-class hardware, so a
# full from-scratch re-run wasn't attempted before this was committed. Treat
# it as a faithful transcription of the working commands, not as separately
# verified. Test on a clean SD card image before trusting it unattended.
#
# Known-fragile step flagged inline: PyGObject==3.46.0 failed on the
# original Nano (no error captured in its bash history, only that the
# session moved on to 3.44.1, which worked) — if 3.44.1 also fails on some
# future image, that needs fresh investigation, not another version guess.
set -euo pipefail

PY_VERSION="3.10.18"
PY_PREFIX="/opt/python310"
VENV_DIR="${HOME}/reachy-venv"
GST_PREFIX="/opt/gstreamer-1.24"
GST_SRC_DIR="${HOME}/gstreamer-1.24-src"
GST_PLUGINS_RS_DIR="${HOME}/gst-plugins-rs"
GST_PLUGINS_RS_REF="0.14.5"

echo "== 1. Build Python ${PY_VERSION} from source =="
if [ ! -x "${PY_PREFIX}/bin/python3.10" ]; then
    sudo apt-get update
    sudo apt-get install -y \
        build-essential wget curl git git-lfs libssl-dev zlib1g-dev \
        libncurses5-dev libncursesw5-dev libreadline-dev libsqlite3-dev \
        libgdbm-dev libdb5.3-dev libbz2-dev libexpat1-dev liblzma-dev \
        libffi-dev uuid-dev tk-dev

    tmpdir="$(mktemp -d)"
    trap 'rm -rf "${tmpdir}"' EXIT
    (
        cd "${tmpdir}"
        wget "https://www.python.org/ftp/python/${PY_VERSION}/Python-${PY_VERSION}.tgz"
        tar xf "Python-${PY_VERSION}.tgz"
        cd "Python-${PY_VERSION}"
        ./configure --prefix="${PY_PREFIX}" --with-ensurepip=install
        make -j"$(nproc)"
        sudo make altinstall
    )
else
    echo "Python already built at ${PY_PREFIX}, skipping."
fi
"${PY_PREFIX}/bin/python3.10" --version

echo "== 2. Create venv + install reachy-mini =="
if [ ! -d "${VENV_DIR}" ]; then
    "${PY_PREFIX}/bin/python3.10" -m venv "${VENV_DIR}"
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip setuptools wheel

# PyGObject/cairo native deps — needed before `pip install reachy-mini`
# pulls in PyGObject, or the build fails on missing girepository headers.
sudo apt-get update
sudo apt-get install -y \
    libcairo2-dev pkg-config libgirepository1.0-dev gobject-introspection \
    libglib2.0-dev libffi-dev

pip install pycairo
# 3.46.0 was tried first and abandoned for 3.44.1 in the original session;
# no captured reason why 3.46.0 failed. Pin the version known to work here.
pip install "PyGObject==3.44.1"
pip install reachy-mini

echo "== 3. udev rules + dialout group (serial access to the Mini's board) =="
sudo tee /etc/udev/rules.d/99-reachy-mini.rules > /dev/null <<'EOF'
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="55d3", MODE="0666", GROUP="dialout"
SUBSYSTEM=="tty", ATTRS{idVendor}=="38fb", ATTRS{idProduct}=="1001", MODE="0666", GROUP="dialout"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG dialout "$(whoami)"
echo "NOTE: group change requires re-login (or 'newgrp dialout') to take effect in this shell."

echo "== 4. Build GStreamer 1.24 from source =="
# Ubuntu 18.04's packaged GStreamer is too old for the daemon's media
# pipeline (webrtcsink etc.) — built from source into ${GST_PREFIX} instead.
if [ ! -d "${GST_SRC_DIR}" ]; then
    echo "ERROR: ${GST_SRC_DIR} not found. This script assumes the GStreamer"
    echo "1.24 source tree (with subprojects checked out) is already present,"
    echo "matching this repo's original clone. Fetch it before continuing:"
    echo "  meson wrap: see https://gitlab.freedesktop.org/gstreamer/gstreamer"
    exit 1
fi
cd "${GST_SRC_DIR}"

# Patch: gstdrmdumb.c fails to compile against this system's (older) libdrm
# headers, which don't define DRM_FORMAT_NV15. Guard both switch cases with
# an #ifdef instead of assuming the constant exists.
PATCH_FILE="subprojects/gst-plugins-base/gst-libs/gst/allocators/gstdrmdumb.c"
if ! grep -q '#ifdef DRM_FORMAT_NV15' "${PATCH_FILE}"; then
    cp "${PATCH_FILE}" "${PATCH_FILE}.bak"
    python3 - "${PATCH_FILE}" <<'PY'
import sys
from pathlib import Path

p = Path(sys.argv[1])
s = p.read_text()
old = "    case DRM_FORMAT_NV15:"
new = "#ifdef DRM_FORMAT_NV15\n    case DRM_FORMAT_NV15:\n#endif"
count = s.count(old)
if count != 2:
    raise SystemExit(f"Expected 2 occurrences of the unpatched line, found {count}; not modifying file.")
p.write_text(s.replace(old, new))
print("Patched:", p)
PY
fi

meson setup build --prefix="${GST_PREFIX}" --buildtype=release || true
meson configure build \
    -Dges=disabled -Ddevtools=disabled -Dpython=disabled \
    -Dintrospection=disabled -Dgst-examples=disabled -Dtests=disabled \
    -Dexamples=disabled -Dbenchmarks=disabled -Dlibav=disabled \
    -Dugly=disabled -Drtsp_server=disabled
meson configure build -Dgst-plugins-bad:aja=disabled
meson compile -C build
meson install -C build

# shellcheck disable=SC2016
cat > "${HOME}/.reachy-gstreamer-env" <<EOF
export GST_ROOT=${GST_PREFIX}
export PATH="\$GST_ROOT/bin:\$PATH"
export LD_LIBRARY_PATH="\$GST_ROOT/lib/aarch64-linux-gnu:\$GST_ROOT/lib:\$LD_LIBRARY_PATH"
export PKG_CONFIG_PATH="\$GST_ROOT/lib/aarch64-linux-gnu/pkgconfig:\$GST_ROOT/lib/pkgconfig:\$GST_ROOT/share/pkgconfig"
export GST_PLUGIN_PATH="/opt/gst-plugins-rs/lib/aarch64-linux-gnu:\$GST_ROOT/lib/aarch64-linux-gnu/gstreamer-1.0:\$GST_ROOT/lib/gstreamer-1.0"
EOF
# shellcheck disable=SC1090
source "${HOME}/.reachy-gstreamer-env"

echo "== 5. Build gst-plugins-rs (webrtc plugin) =="
if ! command -v rustc >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
fi
# shellcheck disable=SC1091
source "${HOME}/.cargo/env"

if [ ! -d "${GST_PLUGINS_RS_DIR}" ]; then
    git clone https://gitlab.freedesktop.org/gstreamer/gst-plugins-rs.git "${GST_PLUGINS_RS_DIR}"
fi
cd "${GST_PLUGINS_RS_DIR}"
git checkout "${GST_PLUGINS_RS_REF}"
cargo install cargo-c
cargo build --release -p gst-plugin-webrtc

plugin_dir="$(pkg-config --variable=pluginsdir gstreamer-1.0)"
sudo install -m 755 target/release/libgstrswebrtc.so "${plugin_dir}/"
rm -f "${HOME}/.cache/gstreamer-1.0/registry.aarch64.bin"

echo "== 6. ALSA config for the Mini's ReSpeaker audio card =="
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python3 - <<'PY'
from reachy_mini.media.audio_utils import (
    get_respeaker_card_number,
    has_reachymini_asoundrc,
    write_asoundrc_to_home,
)

print("Detected audio card:", get_respeaker_card_number())
print("Reachy .asoundrc present:", has_reachymini_asoundrc())

if not has_reachymini_asoundrc():
    write_asoundrc_to_home()
    print("Created ~/.asoundrc")
PY

# A desktop session's PulseAudio can auto-spawn under this user and hold
# the Mini's capture PCM open, blocking the daemon's own ALSA access
# regardless of ~/.asoundrc being correct — found live during Phase 22b
# (see docs/verification/phase-22b-first-motion-2026-09-23.md). Disabling
# autospawn is a one-time per-user config, not something start-reachy.sh
# re-applies on every start.
mkdir -p "${HOME}/.config/pulse"
if [ ! -f "${HOME}/.config/pulse/client.conf" ] || ! grep -q '^autospawn *= *no' "${HOME}/.config/pulse/client.conf"; then
    printf 'autospawn = no\n' >> "${HOME}/.config/pulse/client.conf"
    echo "Set autospawn = no in ~/.config/pulse/client.conf"
fi

echo "== Done =="
echo "Verify with:"
echo "  source ${HOME}/.reachy-gstreamer-env && source ${VENV_DIR}/bin/activate"
echo "  gst-inspect-1.0 webrtcsink"
echo "  reachy-mini-daemon --headless --log-level DEBUG"

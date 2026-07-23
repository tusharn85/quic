# Handover: Building curl with HTTP/3 (QUIC) Support

**Purpose:** Reference for replicating this build on identical pods, and basis for a Dockerfile to bake it into a proper image.

**Reference doc:** https://curl.se/docs/http3.html

**Environment observed:**
- Debian/Ubuntu-based container (`apt-get` used)
- Root filesystem: overlay, read-write
- `/opt` on this pod: read-only (mount-specific — verify per-pod, may differ)
- Install prefix used throughout: **`/usr/local/quictls`**

> ⚠️ Everything below was built directly inside a running pod's writable overlay. It does **not** survive pod restart/rescheduling. Treat this file as the source-of-truth for writing a Dockerfile (see bottom of this document).

---

## 0. Prerequisites

```bash
apt-get update && apt-get install -y \
  build-essential \
  autoconf automake libtool pkg-config git \
  libpsl-dev libidn2-dev zlib1g-dev libbrotli-dev libzstd-dev
```

Notes:
- `build-essential` provides `gcc`/`make` — build fails immediately without it (`gcc: not found`).
- `autoconf`/`automake`/`libtool`/`pkg-config` required for `autoreconf` on nghttp3/ngtcp2/curl.
- `libpsl-dev` etc. avoid curl `./configure` dependency errors later. More may surface depending on curl version (watch for missing libs during `./configure` and install as needed).

---

## 1. Build quictls (OpenSSL fork with QUIC support)

```bash
git clone --depth 1 --branch openssl-4.0.1 https://github.com/openssl/openssl
cd /openssl        # source already present/cloned in this environment
make clean          # if reconfiguring after a failed attempt

./Configure enable-tls1_3 enable-quic \
  --prefix=/usr/local/quictls \
  --openssldir=/usr/local/quictls/ssl \
  shared

make -j$(nproc)
make install_sw      # NOT `make install` — installs libs/binaries only, skips docs (faster, avoids some install-path issues)
```

**Gotchas hit:**
- Original build was misconfigured with `--prefix` effectively pointing at `/usr/bin/openssl`, which collided with the existing system `openssl` **file** → `Cannot create directory /usr/bin/openssl: File exists`. Never install a custom OpenSSL over system paths.
- First attempt at `/opt/quictls` failed: `/opt` was read-only on this pod. Confirmed via `mount | grep opt`. Switched to `/usr/local/quictls`, which is under the writable root overlay.

**Resulting install:**
- Libraries: `/usr/local/quictls/lib64/`
- `openssl` CLI: `/usr/local/quictls/bin/openssl`

---

## 2. Register the new libs with the dynamic linker

```bash
echo "/usr/local/quictls/lib64" > /etc/ld.so.conf.d/quictls.conf
ldconfig
ldconfig -p | grep quictls   # sanity check
```

---

## 3. Build nghttp3

```bash
git clone --depth 1 https://github.com/ngtcp2/nghttp3
cd nghttp3          # git clone https://github.com/ngtcp2/nghttp3 (no branch pinned — default branch)
git submodule update --init
autoreconf -fi
./configure --prefix=/usr/local/quictls --enable-lib-only
make -j$(nproc)
make install
```

**Gotcha hit:** running `make` before `autoreconf -fi`/`./configure` gives `No targets specified and no makefile found` — autotools projects don't ship a pre-generated Makefile.

---

## 4. Build ngtcp2

```bash
cd ngtcp2
autoreconf -fi
./configure PKG_CONFIG_PATH=/usr/local/quictls/lib64/pkgconfig \
  LDFLAGS="-Wl,-rpath,/usr/local/quictls/lib64" \
  --prefix=/usr/local/quictls \
  --with-openssl
make -j$(nproc)
make install
```

---

## 5. Build curl

```bash
cd ..
git clone --depth 1 https://github.com/curl/curl
cd curl
autoreconf -fi
./configure PKG_CONFIG_PATH=/usr/local/quictls/lib64/pkgconfig \
  LDFLAGS="-Wl,-rpath,/usr/local/quictls/lib64" \
  --with-openssl=/usr/local/quictls \
  --with-ngtcp2=/usr/local/quictls \
  --with-nghttp3=/usr/local/quictls
make -j$(nproc)
make install
```

Installs to `/usr/local/bin/curl` and `/usr/local/lib/libcurl.so.4` by default.

**Verify QUIC detection during `./configure` output:**
```
checking for SSL_set_quic_tls_cbs... yes
configure: OpenSSL with QUIC APIv2
```

---

## 6. Fix runtime linking (critical step — easy to miss)

After install, `curl --version` showed a **version mismatch** — new curl binary (`8.22.0-DEV`) but old system `libcurl/7.88.1` and old `OpenSSL/3.0.20`, no `HTTP3` in Features. Root cause: `/usr/local/lib` (new libcurl) wasn't registered with the dynamic linker, so the system's `/lib/x86_64-linux-gnu/libcurl.so.4` was found first — despite the `-rpath` flag on the OpenSSL/ngtcp2/nghttp3 builds.

**Fix — register `/usr/local/lib` too, alongside quictls:**

```bash
echo "/usr/local/lib" > /etc/ld.so.conf.d/local-curl.conf
echo "/usr/local/quictls/lib64" > /etc/ld.so.conf.d/quictls.conf
ldconfig
```

**Verify correct linking:**

```bash
ldd $(which curl) | grep -E "libcurl|libssl|libcrypto|nghttp3|ngtcp2"
```

Expected output (confirmed working):
```
libcurl.so.4 => /usr/local/lib/libcurl.so.4
libnghttp3.so.9 => /usr/local/quictls/lib/libnghttp3.so.9
libngtcp2_crypto_ossl.so.0 => /usr/local/quictls/lib/libngtcp2_crypto_ossl.so.0
libngtcp2.so.16 => /usr/local/quictls/lib/libngtcp2.so.16
libssl.so.4 => /usr/local/quictls/lib64/libssl.so.4
libcrypto.so.4 => /usr/local/quictls/lib64/libcrypto.so.4
```

---

## 7. Final verification

```bash
curl --version
```
Expect: matching curl/libcurl version, `OpenSSL 3.x` (quictls), `HTTP3` in the `Features:` line, `nghttp3/x.x.x ngtcp2/x.x.x` in the version banner.

Functional test against a known HTTP/3 endpoint:

```bash
curl --http3 -v https://cloudflare-quic.com/
```
Look for ALPN negotiating `h3` and `Using HTTP/3` in verbose output.

---

## Quick-copy script for identical pods

For a pod with the same base image/state (build-essential + autotools already installed, `/usr/local` writable, `/opt` read-only), this is the condensed end-to-end sequence assuming source trees are already cloned into `/openssl`, `nghttp3`, `ngtcp2`, `curl` at the same relative locations used above:

```bash
#!/bin/bash
set -e

apt-get update && apt-get install -y \
  build-essential autoconf automake libtool pkg-config git \
  libpsl-dev libidn2-dev zlib1g-dev libbrotli-dev libzstd-dev

# quictls OpenSSL
cd /openssl
./Configure enable-tls1_3 enable-quic \
  --prefix=/usr/local/quictls --openssldir=/usr/local/quictls/ssl shared
make -j$(nproc)
make install_sw

echo "/usr/local/quictls/lib64" > /etc/ld.so.conf.d/quictls.conf
ldconfig

# nghttp3
cd /nghttp3
git submodule update --init
autoreconf -fi
./configure --prefix=/usr/local/quictls --enable-lib-only
make -j$(nproc)
make install

# ngtcp2
cd /ngtcp2
autoreconf -fi
./configure PKG_CONFIG_PATH=/usr/local/quictls/lib64/pkgconfig \
  LDFLAGS="-Wl,-rpath,/usr/local/quictls/lib64" \
  --prefix=/usr/local/quictls --with-openssl
make -j$(nproc)
make install

# curl
cd /curl
autoreconf -fi
./configure PKG_CONFIG_PATH=/usr/local/quictls/lib64/pkgconfig \
  LDFLAGS="-Wl,-rpath,/usr/local/quictls/lib64" \
  --with-openssl=/usr/local/quictls \
  --with-ngtcp2=/usr/local/quictls \
  --with-nghttp3=/usr/local/quictls
make -j$(nproc)
make install

echo "/usr/local/lib" > /etc/ld.so.conf.d/local-curl.conf
ldconfig

curl --version
```

> Adjust source paths (`/openssl`, `/nghttp3`, `/ngtcp2`, `/curl`) to wherever the pod's source trees actually live. If cloning fresh instead of copying pre-cloned trees, add the `git clone` steps from sections 1–5 above before each build block.

---

## Recommended next step: bake this into a container image

Building live inside a running pod is fragile and **ephemeral** — the overlay filesystem changes here are lost on pod restart or rescheduling. This whole sequence should become a **multi-stage Dockerfile**:

- **Build stage:** a full-toolchain base image (e.g. `debian:bookworm`) runs sections 0–5 above.
- **Runtime stage:** copy only the compiled artifacts (`/usr/local/quictls`, `/usr/local/bin/curl`, `/usr/local/lib/libcurl*`) into a slim runtime image, plus the two `ld.so.conf.d` entries, then run `ldconfig` once during image build.
- This makes the HTTP/3 curl build reproducible, versioned, and persistent across pod restarts — and removes the need to install `build-essential`/autotools in the final running image at all.

Ask for a full Dockerfile draft based on this sequence when ready — it can reuse every command in this file directly.

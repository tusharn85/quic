# QUIC Project Setup

Test Setup

- 2 K8s pods - one server, one client
- Server running nginx, client interacting with server via cURL

For TCP, we can use the default `/tmp/nginx.conf`

For QUIC, we need a few prerequisites.

### 1. cURL-QUIC support

Refer `curl-quic [installation.md](http://installation.md/)` for detailed instructions

Run the following script:

```bash
#!/bin/bash
set -e

apt-get update && apt-get install -y \
  build-essential autoconf automake libtool pkg-config git \
  libpsl-dev libidn2-dev zlib1g-dev libbrotli-dev libzstd-dev

# quictls OpenSSL
git clone --depth 1 --branch openssl-4.0.1 https://github.com/openssl/openssl
cd /openssl
./Configure enable-tls1_3 enable-quic \
  --prefix=/usr/local/quictls --openssldir=/usr/local/quictls/ssl shared
make -j$(nproc)
make install_sw

echo "/usr/local/quictls/lib64" > /etc/ld.so.conf.d/quictls.conf
ldconfig
cd ..

# nghttp3
git clone --depth 1 https://github.com/ngtcp2/nghttp3
cd /nghttp3
git submodule update --init
autoreconf -fi
./configure --prefix=/usr/local/quictls --enable-lib-only
make -j$(nproc)
make install
cd ..

# ngtcp2
git clone --depth 1 https://github.com/ngtcp2/ngtcp2
cd /ngtcp2
autoreconf -fi
./configure PKG_CONFIG_PATH=/usr/local/quictls/lib64/pkgconfig \
  LDFLAGS="-Wl,-rpath,/usr/local/quictls/lib64" \
  --prefix=/usr/local/quictls --with-openssl
make -j$(nproc)
make install
cd ..

# curl
git clone --depth 1 https://github.com/curl/curl
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

# Check for HTTP3
curl --version
```

### 2. nginx with HTTP/3 (QUIC) and TLS 0-RTT support

Refer `nginx-quic [installation.md](http://installation.md/)` for detailed instructions

Check if you already have the functionality:

- Look for `--with-http_v3_module` in the output of `nginx -V`

Run the following script:

```bash
#!/bin/bash

# Get Prerequisites
apt-get update
apt-get install -y build-essential git wget libpcre3-dev zlib1g-dev

# Get OpenSSL 3.5.x
cd /usr/local/src
git clone --depth 1 -b openssl-3.5.7 https://github.com/openssl/openssl.git quictls

# Build nginx against OpenSSL
cd /usr/local/src
wget https://nginx.org/download/nginx-1.27.5.tar.gz
tar xzf nginx-1.27.5.tar.gz
cd nginx-1.27.5

./configure \
  --prefix=/etc/nginx \
  --sbin-path=/usr/sbin/nginx \
  --modules-path=/usr/lib/nginx/modules \
  --conf-path=/etc/nginx/nginx.conf \
  --error-log-path=/var/log/nginx/error.log \
  --http-log-path=/var/log/nginx/access.log \
  --pid-path=/run/nginx.pid \
  --lock-path=/run/nginx.lock \
  --http-client-body-temp-path=/var/cache/nginx/client_temp \
  --http-proxy-temp-path=/var/cache/nginx/proxy_temp \
  --http-fastcgi-temp-path=/var/cache/nginx/fastcgi_temp \
  --http-uwsgi-temp-path=/var/cache/nginx/uwsgi_temp \
  --http-scgi-temp-path=/var/cache/nginx/scgi_temp \
  --user=nginx --group=nginx \
  --with-compat --with-file-aio --with-threads \
  --with-http_addition_module --with-http_auth_request_module \
  --with-http_dav_module --with-http_flv_module --with-http_gunzip_module \
  --with-http_gzip_static_module --with-http_mp4_module --with-http_random_index_module \
  --with-http_realip_module --with-http_secure_link_module --with-http_slice_module \
  --with-http_ssl_module --with-http_stub_status_module --with-http_sub_module \
  --with-http_v2_module --with-http_v3_module \
  --with-mail --with-mail_ssl_module \
  --with-stream --with-stream_realip_module --with-stream_ssl_module --with-stream_ssl_preread_module \
  --with-openssl=/usr/local/src/quictls

make -j$(nproc)

# Backup old nginx as fallback
cp /usr/sbin/nginx /usr/sbin/nginx.bak
make install

# Check for --with-http3-module
nginx -V
```

### 3. Changes to `nginx.conf`

For TCP, the default configuration file in the deployment can be used as-is (`/tmp/nginx.conf`)

For QUIC, we need to add a few lines to our configuration file. In the `http` block:

```bash
http3_stream_buffer_size 512m;
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 1d;
ssl_early_data on;                    # 0-RTT
```

In the `server` block:

```bash
listen 1094 quic reuseport;
listen [::]:1094 quic reuseport;
```

---

### Run `curlPull.sh`

Set the Number of Files Parameter to the desired parallel transfers you want to perform. Files are stored in `/var/www/webdav` with the names `traffic_*.bin` . Each file is a symlink of `traffic_0.bin` which is just a 3GB file. Keep as many files as you need for the corresponding number of parallel transfers.

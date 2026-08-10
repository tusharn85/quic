# nginx + HTTP/3 (QUIC) + TLS 0-RTT — Build Notes

Goal: get 0-RTT working on an existing nginx 1.27.5 install, without switching
the base Debian version.

## 1. Check what you already have

`nginx -V` may already show `--with-http_v3_module` in the configure
arguments. If so, HTTP/3/QUIC itself already works — no rebuild needed for
that part. What it depends on is the OpenSSL version it was built against.

## 2. Understand the actual OpenSSL requirement

nginx's docs recommend OpenSSL 3.5.1+ for full QUIC support. The nuance:

- **Any OpenSSL with TLS 1.3** → QUIC/HTTP-3 works.
- **OpenSSL < 3.5.1** → falls back to a compatibility layer: QUIC works,
  but **no 0-RTT / early data**.
- **OpenSSL 3.5.1+, BoringSSL, or LibreSSL** → full support including 0-RTT.

So if you only need HTTP/3 itself, you may not need to rebuild anything. This
process is specifically for adding 0-RTT.

## 3. Avoid quictls — it's a dead end

The commonly-referenced `quictls/openssl` fork is **archived**. It only
tracked OpenSSL up through 3.1.7 before the maintainers moved to a new,
less-mature successor repo. In practice:

- The last tagged release (`openssl-3.3.0+quic`) **fails to compile** —
  `ssl/ssl_quic.c` has broken references (`offset` undeclared, missing
  `QUIC_DATA` struct member). This is a known, reproducible break, not a
  local environment issue.
- It hasn't received a security patch since Feb 2025 — a real concern for
  a TLS library, independent of the build failure.

**Skip quictls. Build vanilla OpenSSL instead.**

## 4. Build vanilla OpenSSL 3.5.x from source

OpenSSL itself gained native QUIC + 0-RTT support starting at 3.5. It's
actively maintained and gets QUIC-specific CVE fixes (3.5.7, for example,
patched a QUIC `PATH_CHALLENGE` memory-growth issue and a QUIC server
initial-packet NULL dereference).

```bash
apt-get update
apt-get install -y build-essential git wget libpcre3-dev zlib1g-dev

cd /usr/local/src
git clone --depth 1 -b openssl-3.5.7 https://github.com/openssl/openssl.git quictls
```

(Directory kept as `quictls` purely so the nginx `--with-openssl` flag below
doesn't need editing — it's vanilla OpenSSL inside, not the fork.)

## 5. Build nginx against it, reusing your existing module list

Pull the matching nginx source and reuse every `--with-*` flag from your
original `nginx -V` output, so the rebuild doesn't drop any module you were
already using (mail, stream, dav, etc.):

```bash
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
```

> Only add `--with-openssl-opt=enable-ktls` if you actually want kernel TLS
> offload. It's unrelated to 0-RTT and adds its own dependency (kernel `tls`
> module + hardware/software support) — skip it unless you specifically
> need it.

## 6. Install, but don't lose track of the running process

```bash
cp /usr/sbin/nginx /usr/sbin/nginx.bak   # backup
make install
nginx -V                                  # confirm: OpenSSL 3.5.7, --with-http_v3_module
```

Two traps to avoid here:

- **`nginx -s reload` is not enough.** Reload only re-reads the config file
  in the *already-running* master process — it does not re-exec against the
  new binary on disk. If nginx runs as the container's foreground process
  (`daemon off;`, PID 1), the only way to actually pick up the new binary is
  a full container/pod restart.
- **Pin the package** so a later `apt upgrade` doesn't silently overwrite
  your custom binary with the stock OpenSSL 3.0 build:
  ```bash
  apt-mark hold nginx
  ```

## 7. Use the correct config file explicitly

If you're not using the compile-time default path, always pass `-c`
explicitly rather than relying on defaults — for every check and every
launch:

```bash
nginx -t -c /path/to/your.conf
nginx -T -c /path/to/your.conf
```

Confirm what the *running* process is actually using:
```bash
cat /proc/1/cmdline | tr '\0' ' '; echo
```
If your custom conf path isn't in there, the container's entrypoint/CMD
needs to be updated to launch nginx with `-c /path/to/your.conf` — otherwise
edits to that file never take effect no matter how many times you restart.

## 8. Config changes for HTTP/3 + 0-RTT

At the `http` block level:
```nginx
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 1d;
ssl_early_data on;
```
The shared session cache matters especially with multiple worker processes
and `reuseport` — a resumed connection can land on a different worker than
the one that issued the ticket, and a per-worker cache would miss most
resumptions, silently falling back to a full handshake.

Per server block:
```nginx
listen <port> quic reuseport;
listen [::]:<port> quic reuseport;
add_header Alt-Svc 'h3=":<port>"; ma=86400';
```

If any location handles non-idempotent requests (PUT/DELETE/POST — e.g. a
WebDAV root), guard it against replay, since 0-RTT early data is inherently
replayable:
```nginx
location / {
    if ($ssl_early_data = 1) {
        return 425;
    }
    ...
}
```

## 9. Verify end to end

```bash
# HTTP/3 negotiates
curl -v --http3 https://your-host:port/ -k

# 0-RTT actually accepted on a second connection
openssl s_client -connect your-host:port -quic -sess_out session.pem
openssl s_client -connect your-host:port -quic -sess_in session.pem -early_data /dev/null
# look for "Early data was accepted" in the second run's output
```

If a 425-guarded location is hit with early data, you should see it
rejected there specifically, while other locations accept it — confirming
the guard is scoped correctly rather than blocking everything.

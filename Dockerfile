FROM ubuntu:20.04

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates bc \
      libbrotli1 libidn2-0 libpcre3 libpsl5 libzstd1 zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY stage/ /
RUN ldconfig \
 && groupadd --system nginx \
 && useradd --system -g nginx -M -s /usr/sbin/nologin nginx \
 && mkdir -p /var/cache/nginx /var/log/nginx /var/www/webdav

COPY nginx.conf /etc/nginx/nginx.conf
COPY curlPull.sh symlinks.sh start.sh /opt/quic/

ENV PATH=/usr/local/bin:/usr/local/quictls/bin:$PATH
EXPOSE 1094/tcp 1094/udp
CMD ["/opt/quic/start.sh"]

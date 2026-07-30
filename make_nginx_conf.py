conf = """# ------------------------------------------------------------
# bears.ceoloide.com
# ------------------------------------------------------------

server {
  set $forward_scheme http;
  set $server         "192.168.1.176";
  set $port           8095;

  listen 80;
  listen [::]:80;

  listen 443 ssl;
  listen [::]:443 ssl;

  server_name bears.ceoloide.com;
  http2 on;

  # Let's Encrypt SSL
  include /etc/nginx/conf.d/include/letsencrypt-acme-challenge.conf;
  include /etc/nginx/conf.d/include/ssl-cache.conf;
  include /etc/nginx/conf.d/include/ssl-ciphers.conf;
  ssl_certificate /etc/letsencrypt/live/bears.ceoloide.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/bears.ceoloide.com/privkey.pem;

  # Block Exploits
  include /etc/nginx/conf.d/include/block-exploits.conf;

  access_log /data/logs/proxy-host-7_access.log proxy;
  error_log /data/logs/proxy-host-7_error.log warn;

  location / {
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $http_connection;
    proxy_http_version 1.1;

    # Proxy!
    include /etc/nginx/conf.d/include/proxy.conf;
  }

  # Custom
  include /data/nginx/custom/server_proxy[.]conf;
}
"""

with open('/data/nginx/proxy_host/7.conf', 'w') as f:
    f.write(conf)

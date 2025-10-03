
sudo podman stop nginx-proxy_proxy_1
sudo podman rm nginx-proxy_proxy_1
sudo podman image rm localhost/nginx-proxy_proxy:latest
sudo podman compose --podman-run-args='--replace' up --force-recreate --detach

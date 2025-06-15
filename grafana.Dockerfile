FROM grafana/grafana:latest

COPY assets/dashboards.yaml /etc/grafana/provisioning/dashboards/
COPY assets/datasources.yaml /etc/grafana/provisioning/datasources/
COPY assets/*.json /var/lib/grafana/dashboards/

ENV GF_INSTALL_PLUGINS="grafana-clock-panel"

USER 1001

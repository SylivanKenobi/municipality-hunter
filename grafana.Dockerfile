FROM grafana/grafana:12.0.1

COPY assets/dashboards.yaml /etc/grafana/provisioning/dashboards/
COPY assets/datasources.yaml /etc/grafana/provisioning/datasources/
COPY assets/total-dashboard.json /var/lib/grafana/dashboards/

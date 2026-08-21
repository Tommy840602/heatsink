# Runtime secrets

Do not commit credentials in this directory. For external webhook delivery, create
`thermoform_alert_webhook_token` with mode `0640`, or point
`THERMOFORM_ALERT_SECRET_DIR` at a separately managed secret directory. Set
`THERMOFORM_ALERT_SECRET_GID` to the file's group ID so the non-root
Alertmanager container can read it without granting access to other users.

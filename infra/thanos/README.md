# Thanos object storage

`object-store.yml` is the deterministic local/CI filesystem adapter. It is not
a production object store and all of its data shares the Compose host's failure
domain.

For production S3, render a credential-free runtime file:

```bash
python scripts/render_thanos_s3_config.py \
  --bucket thermoform-metrics-prod \
  --endpoint s3.ap-northeast-1.amazonaws.com \
  --region ap-northeast-1 \
  --prefix thermoform/metrics \
  --output .runtime/thanos/object-store.yml
```

Set `THERMOFORM_THANOS_OBJECT_STORE_CONFIG` to that file before rendering or
starting Compose. All three Receive processes, Store Gateway, and the singleton
Compactor mount the same configuration path.

The renderer always selects `aws_sdk_auth: true`, TLS, signature v4, content
MD5, and SSE-S3 unless `--sse-kms-key-id` selects SSE-KMS. It deliberately has
no access-key, secret-key, or session-token arguments. Supply credentials via a
platform workload identity, task/instance role, or projected web-identity token.
Do not add static credentials to the generated YAML or `.env` files.

This repository does not provision a bucket, IAM role, KMS key, lifecycle
policy, cross-region replication, or separate failure domains. Those remain
deployment-platform responsibilities. The local backup tool does not back up a
remote S3 bucket.

Compactor defaults to `0d` retention for raw, 5-minute, and 1-hour blocks, so
samples do not age out unless operators explicitly opt in. Normal compaction
can still replace source blocks while preserving their data. Validate a finite
policy before startup:

```bash
python scripts/validate_thanos_retention.py \
  --raw 365d --five-minutes 365d --one-hour 365d
```

All three values must be equal and at least 10 days. Only Compactor should have
delete permission on current block objects; provider lifecycle rules must not
expire those objects independently. Its `thanos-compact-data` volume is scratch
space and is rebuilt from the bucket rather than backed up.

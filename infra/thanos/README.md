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
starting Compose. All three Receive processes and Store Gateway mount the same
configuration path.

The renderer always selects `aws_sdk_auth: true`, TLS, signature v4, content
MD5, and SSE-S3 unless `--sse-kms-key-id` selects SSE-KMS. It deliberately has
no access-key, secret-key, or session-token arguments. Supply credentials via a
platform workload identity, task/instance role, or projected web-identity token.
Do not add static credentials to the generated YAML or `.env` files.

This repository does not provision a bucket, IAM role, KMS key, lifecycle
policy, cross-region replication, or separate failure domains. Those remain
deployment-platform responsibilities. The local backup tool does not back up a
remote S3 bucket.

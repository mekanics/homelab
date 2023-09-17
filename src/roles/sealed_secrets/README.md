# Bitnami Sealed Secrets
`SealedSecrets` allows Kubernetes Secrets that contain sensitive data such as passwords or tokens to be stored in git alongside the rest of the cluster configuration. Credentials are encrypted by the Sealed Secrets controller running in the cluster.


## Creating a Sealed Secret
Given an existing `Secret` containing the sensitive data, we can use the local `kubeseal` CLI tool to generate a `SealedSecret`.


```bash
kubeseal < secret.yml > sealedsecret.yml -o yaml
```

## Info
https://github.com/bitnami-labs/sealed-secrets
# Argo CD

Argo is a GitOps CD (Continuous Delivery) tool, designed for Kubernetes. Argo can retrieve declarative configuration from git repos as state changes, and apply them to the cluster.

## Implementation

Argo-CD works with the repositories located at https://gitlab.com/industrial-banana

The [Service Manifests](https://gitlab.com/industrial-banana/services/argo-service-manifests) repo defines the Argo `Application` and `Project` manifests for cluster-wide services such as ingress routing, certificates, and distributed storage. These definitions specify the location of the [git repos](https://gitlab.com/industrial-banana/services) that contain the actual manifests for those services, which Argo then deploys into the cluster.

The [Application Manifests](https://gitlab.com/industrial-banana/apps/argo-cd) repo defines the Argo `Application` and `Project` manifests for [general application repos](https://gitlab.com/industrial-banana/apps) deployed into the cluster.

## Info

https://argo-cd.readthedocs.io/en/stable/

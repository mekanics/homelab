.POSIX:

default: namespace argocd root

argocd/charts: argocd/Chart.yaml
	cd argocd \
		&& helm dependency update

namespace:
	kubectl create namespace argocd --dry-run=client --output=yaml \
		| kubectl apply -f -

.PHONY: argocd
argocd: argocd/charts
	cd argocd && \
		./apply.sh

# argocd: 
# 	kubectl apply -n argocd \
# 		-f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml


.PHONY: root
root:
	cd root && \
		./apply.sh

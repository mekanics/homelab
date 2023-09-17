.PHONY: about ping facts lint

# Tips: https://tech.davis-hansson.com/p/make
SHELL := bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c
MAKEFLAGS += --warn-undefined-variables
MAKEFLAGS += --no-builtin-rules
ifeq ($(origin .RECIPEPREFIX), undefined)
  $(error This Make does not support .RECIPEPREFIX. Please use GNU Make 4.0 or later)
endif
.RECIPEPREFIX = >

PLAY_CMD=ansible-playbook

# Load the env settings so they can be read into the Ansible config
-include ../.env
.EXPORT_ALL_VARIABLES: ;


############################

default: metal-bootstrap
k3s: k3s-install

############################

about:
> @echo "Kubernetes Homelab Cluster Ansible Configuration"

ping: about
> @echo "Ping test as default deploy user"
> ansible cluster -m ping

facts: about
> @echo "Gather facts on cluster"
> ansible cluster -m setup

lint:
> ansible-lint

############################

metal-bootstrap: about lint
> @echo "Bootstrapping inventory hosts as $${BOOTSTRAP_USER}"
> $(PLAY_CMD) ./00-playbook-bootstrap.yml -u $${BOOTSTRAP_USER} --private-key=$${BOOTSTRAP_SSH_KEY_FILE} #-K --check

############################

k3s-install: about lint
> @echo "Install Kubernetes"
> $(PLAY_CMD) ./01-playbook-k3s-install.yml 

############################

dev:
> k3d cluster start homelab-dev || k3d cluster create --config k3d-dev.yaml
> k3d kubeconfig get homelab-dev > kubeconfig.yaml

clean:
# > k3d cluster delete homelab-dev
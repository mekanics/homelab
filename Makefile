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
-include ./.env
.EXPORT_ALL_VARIABLES: ;


############################

default: host-bootstrap cluster-install cluster-bootstrap lab-bootstrap
dev: cluster-install-dev cluster-bootstrap lab-bootstrap

k3s: cluster-install

############################

about:
> @echo "Kubernetes Homelab Cluster"

ping: about
> @echo "Ping test as default deploy user"
> ansible cluster -m ping

facts: about
> @echo "Gather facts on cluster"
> ansible cluster -m setup

lint:
> ansible-lint

############################

host-bootstrap: about lint
> @echo "Bootstrapping inventory hosts as $${BOOTSTRAP_USER}"
> $(PLAY_CMD) src/00-playbook-bootstrap.yml -u $${BOOTSTRAP_USER} --private-key=$${BOOTSTRAP_SSH_KEY_FILE} --ask-pass #-K --check

############################

cluster-install: about lint
> @echo "Install Kubernetes"
> $(PLAY_CMD) src/01-playbook-k3s-install.yml

cluster-upgrade: about lint
> @echo "Upgrade Kubernetes"
> $(PLAY_CMD) src/01a-playbook-k3s-upgrade.yml

cluster-bootstrap: about lint
> @echo "Configuring Kubernetes cluster-wide services"
> $(PLAY_CMD) src/02-playbook-services.yml

lab-bootstrap: about lint
> @echo "Start the lab Kubernetes cluster-wide services"
> $(PLAY_CMD) src/03-playbook-the-lab.yml

############################

cluster-install-dev: about
> @echo "Start k3d Dev Cluster"
> k3d cluster start homelab-dev || k3d cluster create --config src/k3d-dev.yaml
> k3d kubeconfig get homelab-dev > src/kubeconfig.yaml

############################

reboot:
> $(PLAY_CMD) src/50-playbook-reboot.yml

############################

clean:
> k3d cluster delete homelab-dev
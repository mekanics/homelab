.POSIX:

# env ?= "prod"

default: k3d

# ~/.ssh/id_ed25519_homelab:
# 	ssh-keygen -t ed25519 -f "$@"

# boot: ~/.ssh/id_ed25519_homelab
# 	ansible-playbook \
# 		--inventory inventory.yml \
# 		boot.yml

# cluster:
# 	ansible-playbook \
# 		--inventory inventory.yml \
# 		cluster.yml

# console:
# 	ansible-console \
# 		--inventory inventory.yml

k3d:
	command -v k3d
	k3d cluster create --config k3d-dev.yaml
	k3d kubeconfig get homelab-dev > kubeconfig.yaml

clean: 
	command -v k3d
	k3d cluster delete homelab-dev
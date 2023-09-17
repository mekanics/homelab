.PHONY: about

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

# Load the env settings so they can be read into the Ansible config
-include ./.env
.EXPORT_ALL_VARIABLES: ;


############################

default: metal

metal: about
> make -C metal

############################

about:
> @echo "Kubernetes Homelab Cluster"

############################

dev:
>	@$(MAKE) -C 00_metal -f Makefile dev

clean:
> @$(MAKE) -C 00_metal -f Makefile clean